# Storage Lien Auction API — Product Requirements Document

## 1. Introduction

Self-storage operators face a recurring and legally sensitive problem: when a tenant stops paying rent, the facility must recover its arrears by placing a lien on the abandoned unit, notifying the tenant, waiting out a statutory cure period, and — if the debt is never satisfied — auctioning the unit's contents to the highest bidder. Any surplus raised beyond what the facility is owed belongs to the defaulted tenant, not the facility. This API models that entire pipeline as a marketplace in the style of an online lien-auction platform, spanning the defaulted-unit lien process and notice, the listing of online and onsite auctions, buyer registration and deposits, bidding, the winning-and-cleanout deadline, payment and sales-tax collection, distribution of any overage back to the tenant, settlement to the facility, and the resolution of disputes.

The system exists to make this multi-party, money-moving workflow auditable and deterministic. Every monetary figure is tracked to the cent, every state change is explicit, and the boundaries between the facility's recovery, the platform's commission, and the tenant's surplus are enforced by a strict allocation waterfall. Because timing is legally material — a cure that arrives one instant too late, an auction opened one instant too early — the platform runs on a logical clock that test operators advance explicitly rather than reading wall-clock time. The remainder of this document specifies the global contracts every endpoint honours, the business logic of each lifecycle stage, the endpoint surface, and the catalogue of error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If `X-User-Role` is missing or is not one of the recognised role names, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is recognised but is not permitted to perform the requested operation — or if an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

The system recognises four roles, spelled exactly as follows: `PlatformAdmin`, `FacilityOperator`, `Buyer`, and `Tenant`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The `PlatformAdmin` is the marketplace operator: it onboards facilities, tenants, units, and buyers, drives the logical clock, and adjudicates disputes. The server does not compare a `PlatformAdmin` identifier to any entity's `id`.
- When `X-User-Role` is `FacilityOperator`, `X-User-ID` is the `id` of the acting `Facility`; ownership checks on any resource that references a `Facility` compare the resource's facility foreign key to `X-User-ID`. A `FacilityOperator` owns a `StorageUnit` if and only if the unit's `facility_id` equals `X-User-ID`, and owns downstream lien notices, auctions, sales, and settlements through that unit. The operator drives the lien-to-auction pipeline for its own facility's units.
- When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; ownership checks on any resource that references a `Buyer` compare the resource's buyer foreign key to `X-User-ID`. A buyer may fund its own deposit, bid, retract its own bids, pay, and clean out only its own resources.
- When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource that references a `Tenant` compare the resource's tenant foreign key to `X-User-ID`. A tenant may cure its own unit's default, claim its surplus, and raise disputes.

Both buyers and tenants may raise disputes and supply requested information on a dispute they are party to; all other write operations are partitioned across the roles as described in the workflows of §3 and summarised in the endpoint table of §4.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range of 1 through 100 inclusive, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` reflects the full matching set before pagination and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in the system — facilities, tenants, storage units, lien notices, auctions, buyers, bids, sales, settlements, and disputes — carries a standard set of system-managed fields:

- `id`: a unique, server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created. Note that resource creation timestamps reflect the logical clock described in §2.5, not wall-clock time.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version`: an integer that begins at its initial value and increments by one on every mutation of the resource. This field underpins the optimistic concurrency control of §2.7.

Whenever a workflow mutates a resource — whether directly or as a downstream cascade — that resource's `updated_at` is refreshed and its `version` is incremented. This applies to computed fields as well: when a settlement credits a tenant's `surplus_balance_cents` or a facility's `recovery_balance_cents`, those parent resources are mutated and their `updated_at` and `version` advance accordingly.

### 2.5. The Logical Clock and Temporal Semantics

Because the lien lifecycle is governed by legally significant deadlines, the platform does not read the host machine's wall clock. Instead it maintains a single logical clock. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any call is made the clock holds precisely this default and never falls back to wall-clock time. A `PlatformAdmin` may advance the clock by supplying a target instant as `to_iso8601`; this admin-only test-driving capability sets "now" for every subsequent time-sensitive comparison — cure windows, maturation, auction open and close boundaries, payment deadlines, and cleanout deadlines all read the logical clock.

Timestamps such as a lien notice's `notice_sent_at`, a bid's `placed_at`, and a resource's `created_at` are stamped from the logical clock at the instant of the operation.

### 2.6. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents; there are no fractional cents and no floating-point money. Where a calculation divides or applies a basis-point rate, the result is rounded to a whole number of cents using the round-half-up method (a value whose fractional part is exactly one half rounds away from zero to the next whole cent). The individual calculations in §3 specify precisely which single step within each formula is the rounded step; rounding is never applied more times than those specifications state, and component amounts are rounded before they are summed rather than summing first and rounding the total.

Basis points express a rate as parts of ten-thousand: a `sales_tax_rate_bps` of 800 means 8.00 percent, and a `facility_fee_bps` value is likewise divided by ten thousand when applied. Rates supplied as input, such as `sales_tax_rate_bps` and `facility_fee_bps`, are stored as given.

### 2.7. Optimistic Concurrency Control on Bidding

Placing a bid is the one operation guarded by optimistic concurrency control. A request to place a bid must carry `expected_auction_version`, and this field is required — a bid request that omits it fails body validation. The supplied value is the `version` of the target auction that the client last observed. If `expected_auction_version` does not equal the auction's current `version`, the create is rejected with `ERR_STALE_VERSION` and HTTP status 412.

The purpose is to prevent a bidder from acting on a stale view of the auction. Each accepted bid, each opening, and each closing increments the auction's `version`. If another writer has already advanced the auction's `version` since the client last read it — for example, a prior bid legitimately superseded the high bid and bumped `high_bid_cents` — then the current writer's notion of `min_next_bid_cents` is out of date, and the platform refuses the bid on the stale version rather than accepting a bid computed against a superseded high bid. No other endpoint accepts or requires a version field; endpoints outside bidding perform no OCC check.

### 2.8. Nested Resource Retrieval and Path Validation

Many paths embed one or more resource identifiers — a unit under which lien notices or auctions are listed, a sale under which a settlement is fetched, and so on. When a path contains identifiers, the system validates their existence from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. Existence checking precedes any business-rule evaluation on the target resource.

### 2.9. State Propagation and Cross-Entity Cascades

A single operation frequently mutates more than one entity, and the platform's consistency depends on every cascade firing atomically. Maturing a lien not only advances the lien notice and the unit but also revokes the tenant's access. Closing an auction with a winning bid creates a sale, transitions the losing bids, moves the unit, and places a hold on the winner's deposit. Paying a sale releases the deposit hold, creates and finalizes a settlement, and credits both the tenant's surplus and the facility's recovery balance in the same transaction. Each of these secondary effects is specified in full within the relevant workflow in §3; none is optional, and each mutated resource has its `updated_at` and `version` advanced per §2.4. Where a dispute is upheld, the corresponding financial cascade is reversed by an equal and opposite compensation so that balances return to their pre-settlement state.

### 2.10. Validation Ordering and Error Precedence

When more than one condition could reject a request, the platform evaluates checks in a fixed priority order and returns the error of the first failing check. The global order is: first authentication (a present, known `X-User-Role`, else `ERR_UNAUTHENTICATED`); then authorization, including the ownership match for a role tied to an entity (else `ERR_FORBIDDEN`); then existence of every path identifier, left to right (else `ERR_NOT_FOUND`); then, on list endpoints, pagination bounds (else `ERR_PAGINATION_INVALID`); then, on every create-or-action request that carries a body, presence of required fields, valid enum values, and non-negative integers (else `ERR_VALIDATION`); then the general state check that the target resource is in a state permitting the requested transition (else `ERR_INVALID_STATE`).

After those shared checks, endpoint-specific business rules run in the priority sequence set out in their workflows. The precise ordering matters most on the two endpoints with many guards. For placing a bid, after the shared checks the order is: the auction must be live (`ERR_AUCTION_NOT_LIVE`), then the version must match (`ERR_STALE_VERSION`), then the buyer must not already hold the high bid (`ERR_ALREADY_HIGH_BIDDER`), then the buyer's available deposit must suffice (`ERR_INSUFFICIENT_DEPOSIT`), then the bid amount must clear the minimum (`ERR_BID_TOO_LOW`). For scheduling an auction, after the shared checks the order is: the unit must be matured (`ERR_UNIT_NOT_MATURED`), then the window itself must be valid (`ERR_INVALID_AUCTION_WINDOW`), then the window must not overlap another auction on the same unit (`ERR_AUCTION_WINDOW_CONFLICT`), then any onsite spacing rule must hold (`ERR_ONSITE_SLOT_CONFLICT`).

## 3. Business Logic & Workflows

### 3.1. Onboarding Facilities, Tenants, Units, and Buyers

The marketplace is seeded by the `PlatformAdmin`. A facility is created with a display `name`, a `state_code` (the US state code, retained only for auditing since the tax rate is pinned per facility), a `sales_tax_rate_bps` giving the sales-tax rate in basis points applied to a buyer's taxable amount, and a `facility_fee_bps` giving the facility's auction commission in basis points. A facility's `recovery_balance_cents` — the running total credited back to the facility — begins at zero.

A tenant is registered against a facility by supplying that facility's identifier as `facility_id`, together with the tenant's `full_name` and contact `email`. A newly registered tenant's `access_status` begins as `ACTIVE` and its `surplus_balance_cents` begins at zero. The two `access_status` values are `ACTIVE` and `REVOKED`.

A storage unit is created by naming its `facility_id`, its occupying `tenant_id`, a human-readable `unit_number`, and the `monthly_rent_cents`. A unit's `past_due_balance_cents` starts at zero and is populated at lien-notice time; its `status` begins at `RENTED`. The `status` of a unit progresses through `RENTED`, `LIEN_NOTICED`, `LIEN_MATURED`, `IN_AUCTION`, `SOLD`, and finally the terminal `CLEARED`. A unit also carries two computed lien figures, `lien_amount_provisional_cents` and `lien_amount_final_cents`, both zero until the lien process pins them.

A buyer is registered with a `full_name` and `email`. A buyer's `status` begins at `REGISTERED` and may later become `SUSPENDED`; its three deposit fields — `deposit_available_cents` (un-held funds), `deposit_held_cents` (funds held against an open winning sale), and `deposit_forfeited_cents` (funds cumulatively lost to forfeiture) — all begin at zero. A buyer adds funds to its deposit by supplying an `amount_cents`, which is added to `deposit_available_cents`.

### 3.2. Declaring a Lien, the Cure Window, and Maturation

The lien pipeline begins when a `FacilityOperator` declares a lien on one of its own units, driving the unit from `RENTED` to `LIEN_NOTICED`. This is permitted only while the unit is `RENTED`, and the request must supply a `past_due_balance_cents` that is greater than zero; a non-positive arrears amount is rejected with `ERR_VALIDATION`. The declaration creates a `LienNotice` in `SENT` status, stamps its `notice_sent_at` from the logical clock, records the supplied arrears as the unit's `past_due_balance_cents`, and sets the notice's `cure_deadline` to fourteen days after `notice_sent_at` — the tenant may cure at or before that instant. A lien notice's `status` moves among `SENT`, `CURED`, `MATURED`, and `WITHDRAWN`.

At creation, the notice's provisional lien is pinned. The lien amount is computed as follows: a daily rent is obtained by taking the unit's `monthly_rent_cents`, dividing by thirty, and rounding half up to whole cents — this division is the only rounded step in the calculation. The accrued rent is that daily rent multiplied by a number of accrued days. The lien amount is then the sum of the unit's `past_due_balance_cents`, the accrued rent, a late fee of 5000 cents, and a lien administration fee of 10000 cents. For the provisional variant computed at notice creation, the number of accrued days is exactly the fourteen-day cure period, projecting the accrual through the cure deadline. The result is written to the unit's `lien_amount_provisional_cents`, and the notice's `lien_amount_cents` is set to this provisional figure.

Should the tenant settle up in time, the tenant cures its own unit, returning it from `LIEN_NOTICED` to `RENTED`. Curing is allowed only while the unit is `LIEN_NOTICED` and the unit has a `SENT` lien notice whose `cure_deadline` has not passed — that is, the logical clock now is at or before the `cure_deadline`; an attempt after that instant is rejected with `ERR_CURE_WINDOW_CLOSED`. A successful cure moves the lien notice from `SENT` to `CURED` and resets the unit's `past_due_balance_cents` to zero.

If the cure window closes without payment, the `FacilityOperator` matures the lien — identifying the target notice by its `lien_notice_id` — driving the unit from `LIEN_NOTICED` to `LIEN_MATURED`. Maturation requires the lien notice to still be `SENT` and the logical clock now to be strictly after the `cure_deadline`; maturing at or before the cure deadline is rejected with `ERR_MATURE_TOO_EARLY`. Maturation moves the notice from `SENT` to `MATURED` and recomputes the lien to its final variant: the same formula applies, but the number of accrued days is the whole number of elapsed days from `notice_sent_at` to the maturation instant, obtained by taking the elapsed time and flooring it to whole days. Because maturation happens strictly after the cure deadline, this actual elapsed-day count is at least the fourteen days used for the provisional figure and typically exceeds it. The result is written to the unit's `lien_amount_final_cents`, and the notice's `lien_amount_cents` is updated to this final figure. Maturation also cascades across entities: the tenant's `access_status` flips from `ACTIVE` to `REVOKED`.

### 3.3. Scheduling and Opening Auctions

Once a unit is matured, the `FacilityOperator` schedules one or more auctions for it. Scheduling requires the unit's `status` to be `LIEN_MATURED`; scheduling against any other status is rejected with `ERR_UNIT_NOT_MATURED`. An auction is scheduled by supplying the `unit_id`, the `mode` (either `ONLINE` or `ONSITE`), a `start_at` and `end_at` defining the bidding window, a `reserve_cents` giving the minimum acceptable hammer price, and a `min_increment_cents` giving the minimum raise over the current high bid. The bidding window is half-open, covering `start_at` inclusive up to but not including `end_at`. A newly scheduled auction has `status` `SCHEDULED`; the full set of auction statuses is `SCHEDULED`, `LIVE`, `CLOSED`, `CANCELLED`, and `SETTLED`. Its `high_bid_cents` begins at zero and its `high_bid_id` is null.

Scheduling validates the window and spacing. The window must satisfy `end_at` strictly after `start_at` and `start_at` at or after the logical clock now; a window that ends at or before it starts, or that starts in the past, is rejected with `ERR_INVALID_AUCTION_WINDOW`. Because a single unit may hold several scheduled auctions at once, the platform forbids two auctions on the same unit whose half-open windows overlap, rejecting the conflict with `ERR_AUCTION_WINDOW_CONFLICT`. In addition, any two `ONSITE` auctions held at the same facility — that is, on units sharing the same `facility_id` — must be separated by at least 120 minutes measured edge to edge as a closed interval with that buffer; onsite auctions closer than two hours apart are rejected with `ERR_ONSITE_SLOT_CONFLICT`. Scheduling deliberately does not move the unit: the unit stays `LIEN_MATURED` so that overlapping-window scheduling can still be detected and rejected. The unit flips only when an auction is opened.

Opening an auction advances it from `SCHEDULED` to `LIVE` and simultaneously drives the unit from `LIEN_MATURED` to `IN_AUCTION`. Opening requires the auction to be `SCHEDULED`, the unit to be `LIEN_MATURED`, and the logical clock now to be at or after `start_at`; opening before `start_at` is rejected with `ERR_OPEN_TOO_EARLY`. Because opening consumes the unit's matured status, a unit may hold several scheduled auctions but only one may ever be opened — a second open attempt finds the unit no longer `LIEN_MATURED` and is rejected with `ERR_INVALID_STATE`. Opening increments the auction's `version` by one. (An auction may also move from `SCHEDULED` to the terminal `CANCELLED` through an out-of-scope administrative cancel, which returns a unit to `LIEN_MATURED`; this path is not exposed as a marketplace operation.)

### 3.4. Buyer Deposits and the Bidding Contest

To participate, a buyer must have funded its deposit. Placing a bid is done by a buyer against a live auction, supplying the `auction_id` in the path, the buyer's own `buyer_id`, the `amount_cents` offered, and the `expected_auction_version` described in §2.7. Each bid is stamped with a `placed_at` from the logical clock, which also serves as the tie-break key for high-bid selection. A bid's `status` is one of `ACTIVE`, `OUTBID`, `WINNING`, `LOST`, or `RETRACTED`, and begins as `ACTIVE`.

A bid is accepted only if a sequence of conditions holds, evaluated in the order given in §2.10. The auction must be `LIVE`; a bid on an auction in any other status is rejected with `ERR_AUCTION_NOT_LIVE`. The `expected_auction_version` must match the auction's current `version`, else `ERR_STALE_VERSION`. A buyer who already holds the current high bid may not bid against itself, and such an attempt is rejected with `ERR_ALREADY_HIGH_BIDDER`. The buyer's `deposit_available_cents` must be at least the required deposit of 20000 cents, else `ERR_INSUFFICIENT_DEPOSIT`. Finally, the bid `amount_cents` must be at least the auction's `min_next_bid_cents`, else `ERR_BID_TOO_LOW`.

The auction's high bid is recomputed on every bid, every retraction, and at close. The candidates are exactly the bids belonging to the auction whose `status` is `ACTIVE`. If there are no such candidates, `high_bid_cents` is zero and `high_bid_id` is null. Otherwise the high bid is the candidate with the greatest `amount_cents`; ties on amount are broken in favour of the earliest `placed_at`, and never by identifier. The auction's `min_next_bid_cents` is the `reserve_cents` whenever `high_bid_cents` is zero, and otherwise the `high_bid_cents` plus the `min_increment_cents`. When a new qualifying bid supersedes the standing high bid, the previously leading bid transitions from `ACTIVE` to `OUTBID`, the auction's `high_bid_cents` and `high_bid_id` point at the new bid, and the auction's `version` increments by one.

A buyer may retract one of its own bids, identified by its `bid_id`, while the bid is `ACTIVE` and the auction is `LIVE`, moving the bid to `RETRACTED`. If the retracted bid was the standing high bid, the auction re-selects its high bid over the remaining `ACTIVE` bids using the same selection rule; if no `ACTIVE` bids remain, `high_bid_cents` resets to zero and `high_bid_id` to null.

### 3.5. Closing the Auction and Forming a Sale

A `FacilityOperator` closes a live auction, moving it from `LIVE` to `CLOSED`. Closing requires the auction to be `LIVE` and the logical clock now to be at or after `end_at`; closing before the window ends is rejected with `ERR_AUCTION_NOT_ENDED`. At close the platform performs the high-bid selection over the `ACTIVE` bids and then branches.

In the winning branch — taken when there is at least one `ACTIVE` bid and the `high_bid_cents` is at least the `reserve_cents` — the leading bid transitions from `ACTIVE` to `WINNING` and every other `ACTIVE` bid transitions to `LOST`. A `Sale` is created for the winning buyer with `payment_status` `UNPAID` and `cleanout_status` `PENDING`, recording the `auction_id` and the winning `buyer_id`. The unit moves from `IN_AUCTION` to `SOLD`. The platform holds the required deposit against the winner by reducing that buyer's `deposit_available_cents` by 20000 cents and increasing its `deposit_held_cents` by 20000 cents. Closing increments the auction's `version` by one.

In the no-sale branch — taken when there are zero `ACTIVE` bids, or the `high_bid_cents` is below the `reserve_cents` — every `ACTIVE` bid transitions to `LOST`, no sale is created, and the unit returns from `IN_AUCTION` to `LIEN_MATURED`, making it eligible for re-listing. Closing still increments the auction's `version` by one.

When a sale is created, its monetary charges are computed in a pinned order, rounding each component to whole cents in this exact sequence rather than summing first and rounding once. The sale's `winning_amount_cents` is the hammer price, equal to the auction's `high_bid_cents` at close. First, the `buyer_premium_cents` is the `winning_amount_cents` multiplied by the buyer-premium rate of 1500 basis points, divided by ten thousand and rounded half up. Second, the `sales_tax_cents` is computed on the premium-inclusive base: take the sum of `winning_amount_cents` and `buyer_premium_cents`, multiply by the facility's `sales_tax_rate_bps`, divide by ten thousand, and round half up. Third, the `total_due_cents` is the plain sum of `winning_amount_cents`, `buyer_premium_cents`, and `sales_tax_cents`, with no further rounding.

The sale also records deadlines and a projected surplus at close. Its `payment_deadline` is set to 48 hours after the sale's `created_at`, and its `cleanout_deadline` to three days after the sale's `created_at`. The sale's `estimated_surplus_cents` is the surplus projected at close using the provisional lien, computed by the waterfall of §3.6 with the lien input taken as the unit's `lien_amount_provisional_cents`.

### 3.6. Payment, the Settlement Waterfall, and Surplus

The winning buyer pays the amount owed on its own sale, moving the sale's `payment_status` from `UNPAID` to `PAID`. Payment is permitted only while `payment_status` is `UNPAID`, only while the logical clock now is at or before the `payment_deadline` (a later attempt is rejected with `ERR_PAYMENT_WINDOW_EXPIRED`), and only while the paying buyer's `status` is not `SUSPENDED` (a suspended buyer is rejected with `ERR_BUYER_SUSPENDED`). Paying releases the buyer's deposit hold by reducing `deposit_held_cents` by 20000 cents and restoring `deposit_available_cents` by 20000 cents.

Payment cascades into settlement. The platform creates and finalizes a `Settlement` for the sale, recording the `sale_id` and distributing the hammer price through a three-bucket waterfall filled strictly in order. The settlement's `gross_proceeds_cents` equals the sale's `winning_amount_cents`. Bucket one, `lien_recovered_cents`, is the lesser of the gross proceeds and the lien figure. Bucket two, `facility_fee_cents`, is the lesser of two quantities: the gross proceeds multiplied by the facility's `facility_fee_bps`, divided by ten thousand and rounded half up (this percentage is the only rounded step in the waterfall); and whatever remains of the gross proceeds after the lien bucket. Bucket three, `surplus_cents`, is the gross proceeds minus `lien_recovered_cents` minus `facility_fee_cents`, which is never negative by construction — this is the overage owed to the tenant. A settlement's `status` is `FINALIZED` or `REVERSED`, beginning at `FINALIZED`. For the final settlement persisted at payment, the lien input to the waterfall is the unit's `lien_amount_final_cents`; because the final lien is at least the provisional lien, the final surplus is at most the estimated surplus shown at close.

Finalizing the settlement credits both parties in the same transaction: the tenant's `surplus_balance_cents` increases by the settlement's `surplus_cents`, and the facility's `recovery_balance_cents` increases by the sum of `lien_recovered_cents`, `facility_fee_cents`, and the sale's `buyer_premium_cents`. The paid sale's auction, which was `CLOSED`, then advances to the terminal `SETTLED`.

### 3.7. Cleanout, Forfeiture, and Buyer Suspension

After paying, the winning buyer reports its own unit cleaned out, moving the sale's `cleanout_status` from `PENDING` to `COMPLETED`. Cleanout requires the sale's `payment_status` to be `PAID` — an attempt before payment is rejected with `ERR_SALE_NOT_PAID` — and the `cleanout_status` to be `PENDING`. A completed cleanout drives the unit from `SOLD` to the terminal `CLEARED`. The sale's `cleanout_status` values are `PENDING`, `COMPLETED`, `OVERDUE`, and `VOIDED`, and this axis evolves independently of the `payment_status` axis, whose values are `UNPAID`, `PAID`, `REFUNDED`, and `FORFEITED`.

A `FacilityOperator` may forfeit a sale, and the effect depends on why the sale is being forfeited. When the buyer never paid — the sale is still `UNPAID` and the logical clock now is strictly past the `payment_deadline` — forfeiture moves `payment_status` from `UNPAID` to `FORFEITED` and moves `cleanout_status` from `PENDING` to `VOIDED`. The held deposit is forfeited: the buyer's `deposit_held_cents` is reduced by 20000 cents and its `deposit_forfeited_cents` is increased by 20000 cents, and the facility's `recovery_balance_cents` is increased by that forfeited 20000 cents. The unit returns from `SOLD` to `LIEN_MATURED`, and the buyer's `status` moves from `REGISTERED` to `SUSPENDED`. In the alternate path, where the buyer paid but never cleaned out — the `cleanout_status` is still `PENDING` and the logical clock now is strictly past the `cleanout_deadline` — forfeiture moves `cleanout_status` from `PENDING` to `OVERDUE`.

### 3.8. Disputes, Reversals, and Refunds

Either a tenant or a buyer may raise a dispute against a completed sale or a settlement. A dispute is created with a `subject_type` of either `SALE` or `SETTLEMENT`, a `raised_by` of either `TENANT` or `BUYER`, and a free-text `reason`. When the subject is a sale the dispute carries the `sale_id`; when the subject is a settlement it carries the `settlement_id`. A dispute's `status` begins at `OPEN` and progresses through `UNDER_REVIEW`, may enter `NEEDS_INFO`, and terminates at either `UPHELD` or `DENIED`; its `resolution` is null until it resolves, taking the value `UPHELD` or `DENIED`.

A `PlatformAdmin` begins review of a dispute, identified by its `dispute_id`, moving it from `OPEN` to `UNDER_REVIEW`, permitted only while the dispute is `OPEN`. From `UNDER_REVIEW` the admin may request more information, moving the dispute to `NEEDS_INFO`, permitted only while it is `UNDER_REVIEW`. The party that raised the dispute — a tenant or a buyer — then provides the requested information by supplying a `note`, moving the dispute from `NEEDS_INFO` back to `UNDER_REVIEW`, permitted only while it is `NEEDS_INFO`. This review-and-information cycle between `UNDER_REVIEW` and `NEEDS_INFO` may repeat any number of rounds.

The admin resolves a dispute from `UNDER_REVIEW` by supplying a `decision`. A decision to uphold sets `resolution` to `UPHELD` and moves the dispute to `UPHELD`; a decision to deny sets `resolution` to `DENIED` and moves the dispute to `DENIED`. Resolution is permitted only while the dispute is `UNDER_REVIEW`. Upholding triggers a compensating cascade determined by the dispute's `subject_type`. When the subject is a settlement, that settlement moves from `FINALIZED` to `REVERSED`: the tenant's `surplus_balance_cents` is reduced by the settlement's `surplus_cents`, and the facility's `recovery_balance_cents` is reduced by the sum of `lien_recovered_cents`, `facility_fee_cents`, and `buyer_premium_cents` — exactly reversing the credits made at finalization, and leaving the proceeds identity intact on the reversed record, where `gross_proceeds_cents` still equals `lien_recovered_cents` plus `facility_fee_cents` plus `surplus_cents`. When the subject is a sale, the sale's `payment_status` moves from `PAID` to `REFUNDED`. A denied dispute performs no financial cascade.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or read data return a `200 OK` status code. All endpoints honour the authentication, authorization, and validation ordering of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities` | Create a facility | PlatformAdmin |
| GET | `/facilities/{facility_id}` | Get a facility | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| GET | `/facilities/{id}/tenants` | List a facility's tenants | PlatformAdmin, FacilityOperator |
| POST | `/tenants` | Register a tenant | PlatformAdmin |
| GET | `/tenants/{tenant_id}` | Get a tenant | PlatformAdmin, FacilityOperator, Tenant |
| POST | `/units` | Create a storage unit | PlatformAdmin |
| GET | `/units/{unit_id}` | Get a storage unit | PlatformAdmin, FacilityOperator, Tenant |
| GET | `/units` | List units | PlatformAdmin, FacilityOperator, Tenant |
| POST | `/units/{unit_id}/lien-notices` | Declare a lien and send notice | FacilityOperator |
| POST | `/units/{unit_id}/cure` | Tenant cures the default | Tenant |
| GET | `/lien-notices/{lien_notice_id}` | Get a lien notice | PlatformAdmin, FacilityOperator, Tenant |
| GET | `/units/{id}/lien-notices` | List a unit's lien notices | PlatformAdmin, FacilityOperator, Tenant |
| POST | `/lien-notices/{lien_notice_id}/mature` | Mature the lien after the cure window | FacilityOperator |
| POST | `/auctions` | Schedule an auction for a matured unit | FacilityOperator |
| GET | `/auctions/{auction_id}` | Get an auction | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| GET | `/units/{id}/auctions` | List a unit's auctions | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| POST | `/auctions/{auction_id}/open` | Open bidding | FacilityOperator |
| POST | `/auctions/{auction_id}/close` | Close bidding and settle the outcome | FacilityOperator |
| POST | `/auctions/{auction_id}/bids` | Place a bid | Buyer |
| GET | `/bids/{bid_id}` | Get a bid | PlatformAdmin, FacilityOperator, Buyer |
| GET | `/bids` | List bids | PlatformAdmin, FacilityOperator, Buyer |
| POST | `/bids/{bid_id}/retract` | Retract an active bid | Buyer |
| POST | `/buyers` | Register a buyer | PlatformAdmin |
| GET | `/buyers/{buyer_id}` | Get a buyer | PlatformAdmin, FacilityOperator, Buyer |
| POST | `/buyers/{buyer_id}/fund-deposit` | Add funds to the buyer's deposit | Buyer |
| GET | `/sales/{sale_id}` | Get a sale | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| GET | `/sales` | List sales | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| POST | `/sales/{sale_id}/pay` | Pay total due and finalize settlement | Buyer |
| POST | `/sales/{sale_id}/cleanout` | Report the unit cleaned out | Buyer |
| POST | `/sales/{sale_id}/forfeit` | Forfeit a sale past its deadline | FacilityOperator |
| GET | `/settlements/{settlement_id}` | Get a settlement | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| GET | `/sales/{id}/settlement` | Get the settlement for a sale | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| POST | `/disputes` | Raise a dispute against a sale or settlement | Tenant, Buyer |
| GET | `/disputes/{dispute_id}` | Get a dispute | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| GET | `/disputes` | List disputes | PlatformAdmin, FacilityOperator, Buyer, Tenant |
| POST | `/disputes/{dispute_id}/review` | Begin review | PlatformAdmin |
| POST | `/disputes/{dispute_id}/request-info` | Request more information | PlatformAdmin |
| POST | `/disputes/{dispute_id}/provide-info` | Raiser supplies information | Tenant, Buyer |
| POST | `/disputes/{dispute_id}/resolve` | Resolve the dispute | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_UNIT_NOT_MATURED` | 409 |
| `ERR_INVALID_AUCTION_WINDOW` | 422 |
| `ERR_AUCTION_WINDOW_CONFLICT` | 409 |
| `ERR_ONSITE_SLOT_CONFLICT` | 409 |
| `ERR_AUCTION_NOT_LIVE` | 409 |
| `ERR_ALREADY_HIGH_BIDDER` | 409 |
| `ERR_INSUFFICIENT_DEPOSIT` | 402 |
| `ERR_BID_TOO_LOW` | 409 |
| `ERR_OPEN_TOO_EARLY` | 409 |
| `ERR_AUCTION_NOT_ENDED` | 409 |
| `ERR_CURE_WINDOW_CLOSED` | 409 |
| `ERR_MATURE_TOO_EARLY` | 409 |
| `ERR_BUYER_SUSPENDED` | 409 |
| `ERR_SALE_NOT_PAID` | 409 |
| `ERR_PAYMENT_WINDOW_EXPIRED` | 409 |
