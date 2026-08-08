# Wine-Storage Cellar API — Product Requirements Document

## 1. Introduction

This document specifies the Wine-Storage & Cellar Management API, the system of record for a climate-controlled fine-wine storage facility and the commercial activity that surrounds it. The facility rents physical locker units to members, tracks every bottle they deposit, monitors storage climate, and coordinates the movement of bottles into and out of the cellar. Around that core inventory sit several interlocking commercial workflows: independent appraisal of individual bottles, insurance coverage priced from those appraisals, auction consignment with a broker-mediated negotiation loop, courier-scheduled delivery, and a member wallet that accrues every charge and credit.

The domain is deliberately interdependent. A finite pool of locker units must be reserved, committed, and released as members deposit and withdraw bottles, with a waitlist that promotes members into units as they free up. Money flows through a single append-only ledger whose running total is the member's wallet balance, and several actions are gated on that balance. Because valuation, insurance, and consignment all touch the same bottles, the system enforces segregation of duties on appraisals and optimistic concurrency on the bottle valuation that insurance and consignment depend upon. The requirements below define the entities, their state machines, the arithmetic of every fee and payout, and the precise order in which validations are applied.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that govern every endpoint. Business-process detail lives in Section 3; the two sections are complementary and occasionally restate the same rule from different angles.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well formed but the role is not permitted to perform the requested operation — or a member attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes five roles: `CellarMember`, `CellarManager`, `Appraiser`, `InsuranceAgent`, and `AuctionBroker`.

`CellarMember` is an entity-backed role: when `X-User-Role` is `CellarMember`, the value of `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare that resource's `member_id` to `X-User-ID`. A `CellarMember` may act only on lockers assigned to them, their own bottles, and the movement requests, consignments, insurance policies, waitlist entries, delivery orders, and ledger entries that carry their `member_id`.

The other four roles carry opaque identities. When `X-User-Role` is `CellarManager`, `X-User-ID` is an opaque operator identifier for the facility operator and is not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Appraiser`, `X-User-ID` is likewise an opaque valuator identifier, but the server records it as `created_by_user_id` on any `Appraisal` the appraiser creates and later compares that stored value against the acting `X-User-ID` at finalize time to enforce segregation of duties; it is never compared to any entity's `id`. When `X-User-Role` is `InsuranceAgent` or `AuctionBroker`, `X-User-ID` is an opaque underwriter or broker identifier respectively, recorded at most incidentally and never used as an ownership key.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list responses are sorted by `created_at` in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. When the caller's role is `CellarMember`, every list endpoint is implicitly scoped to that member: rows the member does not own — judged by the resource's own `member_id`, or by the owning `member_id` of the referenced bottle (appraisals) or locker (maintenance windows and climate readings) — are silently excluded from the page and from `total_count`, rather than raising an authorization error.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Most resources also carry three common properties: a `created_at` timestamp set when the resource is first persisted, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that starts at 1 and increments by one on each mutation. All timestamps are ISO 8601 UTC values with three fractional digits.

Two entities are append-only event records and are the exception to the rule above: a `LedgerEntry` and a `ClimateReading` each carry only an `id` and a `created_at`. Neither has an `updated_at` and neither has a `version`; once written, they are immutable and are never mutated in place.

The `version` field is what the optimistic-concurrency mechanism in Section 2.7 reads and writes, and it is the value clients must echo when finalizing an appraisal. Whenever a mutation advances a resource, both its `updated_at` and its `version` move together. Every lifecycle-bearing resource also exposes a `status` field holding its current state as one of the exact uppercase strings enumerated for its entity in Section 3.

### 2.5. The Logical Clock and the Operations Epoch

The system runs on a logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly advanced it holds that value and never falls back to the host's wall-clock. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the new `current_utc`. Any timestamp the system stamps from "the current logical clock" — an appraisal's `effective_date`, a policy's `bound_at`, a bottle's derived drink-window evaluation — reads this logical clock. Resource `created_at` and `updated_at` values are the exception: they are stamped from the host wall-clock as a strictly monotonic value (never the logical clock), so list ordering by `created_at` remains stable regardless of how the logical clock is set.

A second administrative capability advances the operations epoch. Each invocation performs three sweeps in one request: it promotes the front of each waitlist queue into a matching available locker, expires stale offers that were not accepted since the previous epoch, and lapses bound insurance policies whose holder's wallet has gone negative. The response reports three arrays — `promoted_waitlist_ids`, `expired_waitlist_ids`, and `lapsed_policy_ids` — naming exactly the entries affected by that epoch. The behavior of each sweep is detailed in Section 3.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored as integer cents. Wherever a calculation multiplies cents by a rate or multiplier and must reduce the product back to whole cents, the intermediate product is computed to two decimal places and rounded half-up, then taken as integer cents. This half-up rule is applied at every rounding point named in Section 3; where a formula rounds more than once (for example, a per-bottle premium term or a two-step commission-and-platform-fee waterfall), each rounding point is applied independently in the order the formula specifies — the system never sums raw un-rounded terms and rounds once at the end when the formula pins per-term rounding. Pure counting quantities — locker occupancy figures, waitlist positions — are exact integers and are never rounded.

### 2.7. Optimistic Concurrency on Bottle Valuation

Finalizing an appraisal is guarded by optimistic concurrency against the bottle being valued. The finalize request must carry `expected_bottle_version`, a non-optional input field carrying the client's last observed `version` of the target `Bottle`. If that value does not match the bottle's current `version`, the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412). Because finalizing an appraisal supersedes the bottle's prior finalized appraisal, rewrites the bottle's `appraised_value_cents`, and advances the bottle's `version`, a client whose view of the bottle predates a just-finalized appraisal is holding a stale version, and its finalize is refused rather than allowed to overwrite a valuation it never observed. No other endpoint takes a version field; only appraisal finalize participates in this mechanism.

### 2.8. Derived Quantities and Conserved Invariants

Several fields are computed rather than supplied, and the system keeps them reconciled within the same request that disturbs them. A locker tracks three counts that must always sum to its capacity: `occupied_bottles`, `reserved_bottles`, and `free_bottles`, where `free_bottles` equals `capacity_bottles` minus `occupied_bottles` minus `reserved_bottles`. This identity holds at all times — the three counts always add up to `capacity_bottles`. From those counts a locker derives its `occupancy_status`, and any bottle deposit, withdrawal, reservation, or reservation-release recomputes all four together. Section 3 gives the exact aggregation.

A member's `wallet_balance_cents` is likewise derived: it is the running signed sum of every ledger entry posted to that member. Each entry records a `signed_amount_cents` — the entry's `amount_cents` taken as a positive number for a `CREDIT` and as a negative number for a `DEBIT` — and the wallet balance is the sum of those signed amounts across all of the member's entries. A negative wallet balance means the member owes the facility. Because the ledger is append-only, a debit followed by an equal compensating credit leaves the wallet balance unchanged.

### 2.9. Nested Reference Resolution and Ordered Validation

Every request is validated in a fixed priority order, and the first failing check determines the error returned. Authentication comes first: absent or unknown-role headers yield `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the endpoint, or a `CellarMember` acting on a resource whose `member_id` is not its own, yields `ERR_UNAUTHORIZED`. Third, existence: every id in the path and every foreign-key or reference in the body is resolved left-to-right, and the first that does not name an existing resource yields `ERR_NOT_FOUND`. Fourth, body well-formedness: on write endpoints, a missing required field, an illegal enum value, or an integer outside its stated constraint yields `ERR_VALIDATION`. Fifth, on state-transition endpoints, a resource that is not in a legal state for the requested transition yields `ERR_INVALID_STATE`.

Beyond those five universal layers, endpoint-specific gates apply in the order that follows: the segregation-of-duties check on appraisal finalize; the cross-entity member-active check; the cross-entity object-state checks on bottles; the temporal gates; the capacity and occupancy gates; the fiscal gates; and finally the optimistic-concurrency check on appraisal finalize. Each of these is described alongside the workflow it guards in Section 3, and each carries the specific error identified in Section 5.

### 2.10. Cascading State Propagation

Many operations mutate more than one resource, and every such cascade is resolved synchronously inside the triggering request before the response is returned. Suspending a member freezes that member's assigned lockers, cancels the open movement requests on those lockers, and releases the reservations those cancelled intake requests held. Reactivating a member unfreezes those lockers. Settling a consignment marks the bottle sold, detaches it from its locker, recomputes that locker's occupancy, and posts a credit to the seller's wallet. Completing a maintenance window returns the locker to service and clears its climate breach flag. Each of these secondary effects is specified in full in the relevant Section 3 narrative; when any of them mutates a resource that carries a `version`, that resource's `updated_at` and `version` advance as part of the cascade.

## 3. Business Logic & Workflows

This section describes the domain workflows. Related rules are grouped by the business process they belong to, and some parameters for a single operation are introduced in the subsection where they make business sense rather than all in one place.

### 3.1. Member Onboarding, Suspension, and the Wallet Ledger

A facility operator onboards a member by supplying the member's `full_name`, contact `email` (which is unique across members), and a `membership_tier` of `STANDARD`, `PREMIUM`, or `RESERVE`. A newly onboarded member begins life in `PENDING` status with a `wallet_balance_cents` of 0. Activation moves the member from `PENDING` to `ACTIVE`. All four member lifecycle transitions — activate, suspend, reactivate, and close — are performed by a `CellarManager`; each requires the member to be in the state from which that transition departs, and a member that is not in the departing state is refused with `ERR_INVALID_STATE`.

Suspension takes an `ACTIVE` member to `SUSPENDED` and triggers a three-hop cascade resolved within the request. First, every locker owned by the member (matching on `member_id`) that is currently `ASSIGNED` transitions to `FROZEN`. Second, for each such newly frozen locker, every movement request on it that is still `REQUESTED` or `APPROVED` transitions to `CANCELLED`. Third, for each intake request thus cancelled, the locker's `reserved_bottles` is recomputed so the cancelled request no longer counts, which raises the locker's `free_bottles`. A frozen locker rejects new intake and withdrawal activity for as long as it is `FROZEN`.

Reactivation returns a `SUSPENDED` member to `ACTIVE` and unfreezes their lockers: every locker owned by the member that is `FROZEN` transitions back to `ASSIGNED`. The movement requests cancelled during suspension are not resurrected — reactivation restores only the lockers, not the reservations.

Closing a member is available from either `ACTIVE` or `SUSPENDED` and moves the member to the terminal `CLOSED` state. Two guards apply after the state check. The member may not still hold any locker in `ASSIGNED`, `FROZEN`, or `MAINTENANCE`; if one exists, the close is refused with `ERR_MEMBER_HAS_ACTIVE_LOCKERS`. The member's `wallet_balance_cents` must be at least 0 — a member who still owes the facility, whose balance is below zero, is refused with `ERR_OUTSTANDING_BALANCE`. The active-locker guard is evaluated before the outstanding-balance guard.

Charges and credits reach a member through the ledger. A `CellarManager` may post a manual ledger adjustment by supplying an `entry_type` of `DEBIT` or `CREDIT`, a positive `amount_cents` (at least 1), a human-readable `reason`, and optionally a `related_entity_type` and `related_entity_id` naming the originating record (for example, an `InsurancePolicy` or a `Consignment`). Each posted `LedgerEntry` records its `signed_amount_cents` — positive `amount_cents` for a `CREDIT`, negative for a `DEBIT` — and the member's `wallet_balance_cents` is recomputed as the signed sum across all their entries. Ledger entries are immutable append-only records readable individually or as a member-scoped list filtered by `member_id` and `entry_type`.

### 3.2. Locker Provisioning, Occupancy, and Storage Fees

A `CellarManager` creates a locker by supplying a human `label` or bin code, a `size_tier` of `SMALL`, `MEDIUM`, or `LARGE`, a `climate_zone` of `RED`, `WHITE`, or `SPARKLING`, and a `capacity_bottles` count of at least 1. A new locker is `AVAILABLE`, has no owning member, and reports `occupancy_status` `VACANT` and `climate_status` `NOMINAL`. Its `monthly_fee_cents` is computed at creation from the storage-fee rule below.

The occupancy counts are always derived, never supplied. A locker's `occupied_bottles` is the count of bottles whose `locker_id` points at it and whose status is `STORED`. Its `reserved_bottles` is the sum of the `quantity` of every intake movement request on the locker that is currently `REQUESTED` or `APPROVED`. Its `free_bottles` is `capacity_bottles` less `occupied_bottles` less `reserved_bottles`. The `occupancy_status` is `VACANT` when `occupied_bottles` is zero; it is `FULL` when `occupied_bottles` is greater than or equal to `capacity_bottles`; otherwise it is `PARTIAL`. Note the boundary: a locker whose stored count reaches capacity is `FULL`, not merely partial. Any event that changes a stored bottle's placement in the locker, or that adds or removes a `REQUESTED`/`APPROVED` intake reservation, recomputes all of these figures together.

The monthly storage fee for a locker is a tiered price driven by three interacting inputs — its size tier, its climate zone, and its current occupancy. The base rate is 2,000 cents for a `SMALL` locker, 3,500 cents for a `MEDIUM`, and 6,000 cents for a `LARGE`. The climate multiplier is 1.00 for a `RED` zone, 1.15 for a `WHITE` zone, and 1.30 for a `SPARKLING` zone. A full-occupancy surcharge of ten percent applies only while the locker's `occupancy_status` is `FULL`; otherwise no surcharge applies. The raw fee is the base rate multiplied by the climate multiplier, multiplied by one plus the surcharge fraction (so by 1.10 when full, by 1.00 otherwise). That raw value is rounded half-up to two decimal places and taken as integer cents, then clamped so that it is never below a floor of 2,500 cents and never above a cap of 9,000 cents. The fee is recomputed whenever a locker is created, whenever its occupancy status changes, and during the operations epoch.

Assigning a locker moves it from `AVAILABLE` to `ASSIGNED`. The request names the target `member_id`; that member must be `ACTIVE`, and a locker assignment to a member who is not active is refused with `ERR_MEMBER_NOT_ACTIVE`. On assignment the locker's owning `member_id` is set and its `version` advances. Releasing a locker moves it from `ASSIGNED` back to `AVAILABLE`, but only if it is completely unencumbered: both `occupied_bottles` and `reserved_bottles` must be zero, and a release attempted while either count is non-zero is refused with `ERR_LOCKER_NOT_EMPTY`. Release clears the owning `member_id` and advances the locker's `version`. Retiring a locker moves it from `AVAILABLE` to the terminal `RETIRED` state and is permitted only when `occupied_bottles` is zero. All three of these transitions are performed by a `CellarManager`. A locker also moves to and from `FROZEN` and `MAINTENANCE` under system control, as described in the member-suspension cascade and the maintenance workflow; while `FROZEN`, `MAINTENANCE`, or `RETIRED`, a locker refuses new bottle creation and movement approval.

### 3.3. Storing Bottles, Drink Windows, and Movement Requests

A bottle enters the cellar when a `CellarMember` (or a `CellarManager` acting on the member's behalf) deposits it into an assigned locker. The deposit names the target `locker_id` and describes the wine: its `wine_name` (producer and cuvée label), `vintage_year`, `varietal`, and `format_ml`, which must be one of 375, 750, 1500, or 3000 millilitres. The deposit also records the drinking window as `drink_window_start_year` and `drink_window_end_year`. Provenance may be supplied as `provenance_status`; when omitted it defaults to `UNVERIFIED`, and it is otherwise one of `DOCUMENTED`, `UNVERIFIED`, or `DISPUTED`. A stored bottle begins in `STORED` status, inherits its owning `member_id` from the locker's owner, and carries a starting `appraised_value_cents` of 0 until an appraisal is finalized against it. Depositing recomputes the locker's occupancy figures.

A deposit consumes one free unit of the locker, so it is refused with `ERR_LOCKER_CAPACITY_EXCEEDED` when the locker has no free capacity — that is, when `free_bottles` would be driven below zero; a locker whose `free_bottles` is already zero blocks the deposit at that boundary. A deposit into a locker that is `FROZEN`, `MAINTENANCE`, or `RETIRED` is refused with `ERR_LOCKER_IN_MAINTENANCE`. Provenance can be revised after the fact: a `CellarManager` or an `Appraiser` may set a bottle's `provenance_status` to a new value through the chain-of-custody update.

A bottle's `drink_window_status` is derived by comparing the year of the current logical clock to its window. When the current year is earlier than `drink_window_start_year` the status is `TOO_YOUNG`; when the current year is later than `drink_window_end_year` the status is `PAST_PEAK`; otherwise — including the boundary years where the current year equals the start year or the end year — the status is `IN_WINDOW`. This computed status is exposed when the bottle is read and gates consignment listing, as described in Section 3.7.

Bottles move into and out of storage through movement requests. A `CellarMember` opens a request naming the `member_id`, the affected `locker_id`, a `request_type` of `INTAKE` or `WITHDRAWAL`, and a `quantity` of at least 1. An `INTAKE` request reserves units for future deposits; a `WITHDRAWAL` request pulls specific bottles out, so it must carry `bottle_ids`, and its `quantity` equals the number of bottles listed. Each withdrawal bottle must be `STORED` and currently sit in the named `locker_id`; this condition is enforced at completion (yielding `ERR_BOTTLE_NOT_STORED`), while request creation validates only that each named `bottle_id` exists and that `quantity` equals the number of `bottle_ids` — it does not at creation verify the bottles' status, placement, or ownership. A new request starts in `REQUESTED`. When the request is an intake, its reserved units are immediately reflected in the locker's `reserved_bottles`, and an intake whose reservation would drive the locker's `free_bottles` below zero is refused with `ERR_LOCKER_CAPACITY_EXCEEDED`.

Movement requests follow a branching lifecycle managed by a `CellarManager`, except cancellation which a `CellarMember` may also perform. Approval moves a request from `REQUESTED` to `APPROVED`, but only when the requesting member is `ACTIVE` — otherwise `ERR_MEMBER_NOT_ACTIVE` — and the locker is not `FROZEN`, `MAINTENANCE`, or `RETIRED` — otherwise `ERR_LOCKER_IN_MAINTENANCE`. Rejection moves a `REQUESTED` request to `REJECTED`; if it was an intake, the locker's `reserved_bottles` is recomputed so the request drops out and `free_bottles` rises. Completion moves an `APPROVED` request to `COMPLETED`: for a withdrawal, every listed bottle must still be `STORED` and sit in the request's locker — any that is not yields `ERR_BOTTLE_NOT_STORED` — and on success each listed bottle transitions from `STORED` to `WITHDRAWN`, its `locker_id` is cleared, and the source locker's occupancy is recomputed; for an intake, the reservation is released and those units become available for new deposits. Cancellation moves a request that is `REQUESTED` or `APPROVED` to `CANCELLED`, and again, if it was an intake, the reservation is released and `free_bottles` rises.

### 3.4. The Waitlist and the Operations Epoch

When no locker of the kind a member wants is free, the member joins a waitlist. A `CellarMember` creates a waitlist entry naming their `member_id`, a `requested_size_tier`, and a `requested_climate_zone`. The entry begins in `WAITING`. Its `position` is a one-based rank derived on the fly: among all `WAITING` entries that share the same `requested_size_tier` and `requested_climate_zone`, entries are ordered by `created_at` ascending, and the entry's position is its index in that order. Ordering is by creation time only — there is no secondary tie-break, because each entry's `created_at` is unique. A member reading their entry sees this computed `position`.

Waitlist advancement happens during the operations epoch and only there. For each distinct size-and-climate queue, the epoch promotes the position-one `WAITING` entry into a matching `AVAILABLE` locker — one whose `size_tier` equals the requested size and whose `climate_zone` equals the requested zone. Promotion moves the entry from `WAITING` to `OFFERED` and records the matched locker on the entry as its `offered_locker_id`. The identifiers of every entry promoted in the epoch are returned in `promoted_waitlist_ids`. At most one waiting entry per size-and-climate queue is promoted per epoch (the position-one entry), and where more than one `AVAILABLE` locker matches a queue the oldest by `created_at` is chosen. Within a single epoch the promotion sweep runs before the expiry sweep, and a locker held by an offer still standing at the start of the epoch is not an eligible promotion candidate even though that offer is about to be expired in the same epoch — its released locker only becomes available for promotion in a later epoch. An entry that was already `OFFERED` at the start of an epoch but was not accepted in the interim is considered stale: the epoch expires it, moving it from `OFFERED` to `EXPIRED` and releasing its offered locker back into the pool of `AVAILABLE` candidates; those identifiers are returned in `expired_waitlist_ids`.

An offered member claims their locker by accepting the entry, which moves it from `OFFERED` to the terminal `FULFILLED`. The offered locker must still be `AVAILABLE` at the moment of acceptance; if it has been taken in the meantime, the accept is refused with `ERR_INVALID_STATE`. On success the offered locker transitions from `AVAILABLE` to `ASSIGNED` and its owning `member_id` is set to the waitlisted member. A member may instead cancel an entry that is `WAITING` or `OFFERED`, moving it to `CANCELLED`; if the entry was `OFFERED`, its offered locker is released back to `AVAILABLE`. Both accept and cancel are `CellarMember` operations.

### 3.5. Appraisal and Valuation

Bottles are valued by independent appraisers. An `Appraiser` creates an appraisal naming the `bottle_id`, a valuation `method`, and a raw `base_value_cents` of at least 0. The method is a variant selector: under `MARKET_COMPARABLE` the `assessed_value_cents` is the `base_value_cents` as-is, taken as an auction comparable with no uplift; under `REPLACEMENT_COST` the `assessed_value_cents` is the `base_value_cents` multiplied by a replacement uplift of 1.20, rounded half-up to integer cents. So the same `base_value_cents` yields a higher assessed value under replacement cost than under market comparable. A new appraisal is `DRAFT`, has no `effective_date` yet, and records the acting appraiser's identity as `created_by_user_id`.

Finalization is the segregation-of-duties gate. Only an `Appraiser` may finalize, the appraisal must be `DRAFT`, and the acting `X-User-ID` must differ from the appraisal's `created_by_user_id` — an appraiser finalizing their own draft is refused with `ERR_SEGREGATION_OF_DUTIES`. The finalize request also carries `expected_bottle_version`, and the optimistic-concurrency check of Section 2.7 applies: a mismatch against the bottle's current `version` yields `ERR_STALE_VERSION`. The segregation-of-duties check is evaluated before the stale-version check.

On successful finalization the appraisal moves from `DRAFT` to `FINALIZED`. Any prior `FINALIZED` appraisal for the same bottle transitions from `FINALIZED` to the terminal `SUPERSEDED`, so a bottle has at most one live finalized appraisal at a time. The bottle's `appraised_value_cents` is rewritten to this appraisal's `assessed_value_cents`, the appraisal's `effective_date` is stamped from the current logical clock, and the bottle's `version` is incremented — which is precisely why a concurrent client holding the pre-finalize version is turned away. A bottle's `appraised_value_cents` therefore always reflects the latest finalized appraisal, or remains 0 if none exists.

### 3.6. Insurance Quoting, Binding, and Lapse

An `InsuranceAgent` quotes a policy for a member by naming the `member_id`, a `coverage_tier` of `BASIC` or `FULL`, and the `covered_bottle_ids` to be insured. Every covered bottle must belong to the named member; a policy referencing a bottle the member does not own is refused with `ERR_BOTTLE_NOT_OWNED`. A quoted policy computes two figures at quote time and begins in `QUOTED` status with no `bound_at` timestamp.

The `insured_value_cents` is the sum of `appraised_value_cents` across the covered bottles. The annual `premium_cents` is built one bottle at a time and then summed, and the order matters: for each covered bottle a per-bottle rate is formed by multiplying a provenance base rate by a coverage-tier factor, then that rate is applied to the bottle's `appraised_value_cents` and the resulting term is rounded half-up to integer cents; the policy premium is the sum of those already-rounded per-bottle terms, not the single rounding of a raw total. The provenance base rate is 0.015 for a `DOCUMENTED` bottle, 0.025 for an `UNVERIFIED` bottle, and 0.040 for a `DISPUTED` bottle. The coverage-tier factor is 0.5 for `BASIC` coverage and 1.0 for `FULL` coverage. A policy covering no bottles has a `premium_cents` of 0.

Binding a policy moves it from `QUOTED` to `BOUND` and is where money changes hands. The bind is permitted only if the member can afford it against the overdraft floor: the member's `wallet_balance_cents` minus the policy `premium_cents` must be at least the wallet floor of −100,000 cents; a bind that would drop the wallet below that floor is refused with `ERR_INSUFFICIENT_FUNDS`. On a successful bind, a `DEBIT` ledger entry for the `premium_cents` is posted to the member (lowering the wallet balance) and the policy's `bound_at` is stamped from the current logical clock. Cancelling a policy that is `QUOTED` or `BOUND` moves it to `CANCELLED`; if the policy had been bound, a compensating `CREDIT` ledger entry for the same `premium_cents` is posted, returning the wallet to its pre-bind value. Binding and cancelling are `InsuranceAgent` operations.

A bound policy can also lapse without agent action. During the operations epoch, any `BOUND` policy whose holder's `wallet_balance_cents` has gone negative transitions from `BOUND` to the terminal `LAPSED`, and its identifier is reported in `lapsed_policy_ids`.

### 3.7. Consignment, Negotiation, and Settlement

A member may consign a stored bottle for auction. A `CellarMember` opens a consignment naming the `bottle_id` and a `reserve_price_cents` of at least 0 — the minimum acceptable price. The consignment begins in `DRAFT`, and its owning `member_id` is copied from the bottle's owner rather than supplied. Listing is performed by an `AuctionBroker` and is gated on the bottle's condition: the consignment must be `DRAFT`, the bottle must be `STORED` (otherwise `ERR_BOTTLE_NOT_STORED`), its `provenance_status` must be `DOCUMENTED` (otherwise `ERR_PROVENANCE_NOT_DOCUMENTED`), and its drink window must be open — a bottle whose `drink_window_status` is `TOO_YOUNG` is refused with `ERR_DRINK_WINDOW_NOT_OPEN`. Listing moves the consignment from `DRAFT` to `LISTED` and transitions the bottle from `STORED` to `CONSIGNED`.

Negotiation is a cyclic loop between broker and seller. From `LISTED` or `COUNTERED`, the `AuctionBroker` records an offer, supplying `offer_price_cents` and moving the consignment to `OFFERED`. From `OFFERED`, the `CellarMember` may counter, supplying `counter_price_cents` and moving it to `COUNTERED`; the broker may then offer again, and the `OFFERED` and `COUNTERED` states can alternate any number of times. From `OFFERED`, the seller may instead accept. Acceptance requires the current `offer_price_cents` to be at least the `reserve_price_cents`; an offer below reserve is refused with `ERR_OFFER_BELOW_RESERVE`. Acceptance moves the consignment to `ACCEPTED` and writes a provisional payout estimate into `estimated_proceeds_cents`, computed by the proceeds waterfall below over the accepted `offer_price_cents`; the provisional computation touches neither the ledger nor the bottle.

Settlement is performed by the `AuctionBroker` and requires an `ACCEPTED` consignment. The broker supplies the final `hammer_price_cents`, which must itself be at least the `reserve_price_cents` — a hammer below reserve is refused with `ERR_OFFER_BELOW_RESERVE`. Settlement records the `hammer_price_cents`, computes the final payout waterfall over it (writing both `commission_pct` and `net_proceeds_cents`), and then cascades: the bottle transitions from `CONSIGNED` to the terminal `SOLD` with its `locker_id` cleared, the source locker's `occupied_bottles`, `free_bottles`, and `occupancy_status` are recomputed, and a `CREDIT` ledger entry for the `net_proceeds_cents` is posted to the seller, raising their `wallet_balance_cents`. Settlement moves the consignment to the terminal `SETTLED`.

The proceeds waterfall is evaluated in a pinned order over a single price — the `offer_price_cents` for the provisional estimate at acceptance, the `hammer_price_cents` for the final payout at settlement. First, the `commission_pct` is selected by price tier: the fraction is 0.20 when the price is at most 5,000,000 cents, 0.15 when the price is greater than that but at most 20,000,000 cents, and 0.10 when the price exceeds 20,000,000 cents. Second, the commission is the price multiplied by that fraction, rounded half-up to integer cents. Third, the net is the price minus the commission. Fourth, a platform fee is the net multiplied by three percent, rounded half-up to integer cents. Fifth, the proceeds are the net minus the platform fee. The provisional run stores that result in `estimated_proceeds_cents`; the final run stores the selected fraction in `commission_pct` and the result in `net_proceeds_cents`.

A seller may withdraw a consignment at any non-terminal stage — that is, while it is `DRAFT`, `LISTED`, `OFFERED`, or `COUNTERED` — moving it to the terminal `WITHDRAWN`. If the bottle had been placed on consignment (its status is `CONSIGNED`), withdrawal returns it from `CONSIGNED` to `STORED`. Withdrawal is a `CellarMember` operation.

### 3.8. Delivery and Courier Scheduling

Withdrawn bottles leave the facility on scheduled deliveries. A `CellarManager` schedules a delivery order naming the recipient `member_id`, the `bottle_ids` to deliver, a `courier_ref` identifying the courier resource, and a delivery window bounded by `slot_start` and `slot_end`. The window is half-open, covering `slot_start` inclusive up to `slot_end` exclusive. Every bottle listed must belong to the member and must currently be `WITHDRAWN`. The ownership check is applied first, across all listed bottles — a bottle not owned by the member is refused with `ERR_BOTTLE_NOT_OWNED` — and only after every bottle passes ownership is the withdrawn-status check applied, a bottle not currently `WITHDRAWN` being refused with `ERR_DELIVERY_BOTTLE_NOT_WITHDRAWN`.

Delivery windows must not collide on a shared courier. A new order conflicts with any existing non-cancelled delivery order on the same `courier_ref` when the new window's start falls before the existing window's end and the existing window's start falls before the new window's end. Because the intervals are half-open, exact adjacency is permitted — a new window that starts exactly when another ends, or ends exactly when another starts, does not conflict. A conflicting order is refused with `ERR_COURIER_SLOT_CONFLICT`. On a successful schedule the order begins in `SCHEDULED` and each listed bottle transitions from `WITHDRAWN` to `IN_TRANSIT`.

Marking a delivery delivered moves the order from `SCHEDULED` to the terminal `DELIVERED` and transitions each of its bottles from `IN_TRANSIT` to the terminal `DELIVERED`. Cancelling a delivery moves the order from `SCHEDULED` to the terminal `CANCELLED` and returns each of its bottles from `IN_TRANSIT` back to `WITHDRAWN`, restoring them to the pool of bottles awaiting delivery. Both transitions are `CellarManager` operations.

### 3.9. Climate Monitoring and Maintenance Windows

Storage conditions are monitored through climate readings. A `CellarManager` records a reading for a locker with a measured `temperature_c` and `humidity_pct`. The reading is judged in-band and its `in_band` flag set true only when the temperature is between 10.0 and 16.0 degrees Celsius inclusive and the humidity is between 60.0 and 80.0 percent inclusive; a reading outside either inclusive band is out-of-band. An out-of-band reading flips the monitored locker's `climate_status` to `BREACH`. Climate readings are immutable append-only records.

Maintenance is scheduled against a locker as a closed time window. A `CellarManager` schedules a window naming the `locker_id`, a `window_start` and `window_end` (a closed interval covering both endpoints), and a `reason` work-order note. Maintenance windows on the same locker must be separated by a buffer of 120 minutes: a new window conflicts with any existing non-cancelled window on the locker when the new window's start is at or before the existing window's end plus 120 minutes and the existing window's start is at or before the new window's end plus 120 minutes. Unlike courier slots, adjacency and near-adjacency within the buffer are rejected here. A conflicting window is refused with `ERR_MAINTENANCE_WINDOW_CONFLICT`. A new window begins in `SCHEDULED`.

Activating a window moves it from `SCHEDULED` to `ACTIVE` and puts the locker into maintenance: a locker that was `AVAILABLE`, `ASSIGNED`, or `FROZEN` transitions to `MAINTENANCE` (a locker already in `MAINTENANCE` stays put). Activation is refused with `ERR_INVALID_STATE` if the locker is `RETIRED`. While a locker is in `MAINTENANCE` it refuses bottle creation and movement activity. Completing a window moves it from `ACTIVE` to the terminal `COMPLETED` and returns the locker to service: the locker leaves `MAINTENANCE` for `ASSIGNED` if it still has an owning `member_id`, or for `AVAILABLE` if it does not, and in either case its `climate_status` is reset to `NOMINAL` — completing maintenance is what clears a prior breach. Cancelling a `SCHEDULED` window moves it to the terminal `CANCELLED` with no effect on the locker. All three maintenance transitions are `CellarManager` operations.

## 4. Endpoint Definitions

The table below lists every endpoint with its authorized roles. Endpoints that create a new resource return HTTP 201; endpoints that read or that modify an existing resource (including all state transitions) return HTTP 200. Request and response bodies are not repeated here — the fields each operation consumes and the effects it produces are described in the Section 3 narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/members` | Onboard a member (starts `PENDING`, wallet 0) | `CellarManager` |
| GET | `/members/{memberId}` | Read a member | `CellarMember`, `CellarManager`, `Appraiser`, `InsuranceAgent`, `AuctionBroker` |
| GET | `/members` | List members (filter by tier/status) | `CellarManager`, `InsuranceAgent`, `AuctionBroker` |
| POST | `/members/{memberId}/activate` | `PENDING` → `ACTIVE` | `CellarManager` |
| POST | `/members/{memberId}/suspend` | `ACTIVE` → `SUSPENDED` with locker/reservation cascade | `CellarManager` |
| POST | `/members/{memberId}/reactivate` | `SUSPENDED` → `ACTIVE`, unfreeze lockers | `CellarManager` |
| POST | `/members/{memberId}/close` | `ACTIVE`/`SUSPENDED` → `CLOSED` | `CellarManager` |
| POST | `/members/{memberId}/ledger-adjustments` | Post a manual ledger entry; recompute wallet | `CellarManager` |
| GET | `/ledger-entries/{ledgerEntryId}` | Read a ledger entry | `CellarMember`, `CellarManager`, `InsuranceAgent`, `AuctionBroker` |
| GET | `/ledger-entries` | List ledger entries for a member | `CellarMember`, `CellarManager`, `InsuranceAgent`, `AuctionBroker` |
| POST | `/lockers` | Create an `AVAILABLE` locker | `CellarManager` |
| GET | `/lockers/{lockerId}` | Read a locker | `CellarMember`, `CellarManager`, `Appraiser`, `InsuranceAgent`, `AuctionBroker` |
| GET | `/lockers` | List lockers | `CellarMember`, `CellarManager`, `Appraiser`, `InsuranceAgent`, `AuctionBroker` |
| POST | `/lockers/{lockerId}/assign` | `AVAILABLE` → `ASSIGNED` to an active member | `CellarManager` |
| POST | `/lockers/{lockerId}/release` | `ASSIGNED` → `AVAILABLE` (empty only) | `CellarManager` |
| POST | `/lockers/{lockerId}/retire` | `AVAILABLE` → `RETIRED` (empty only) | `CellarManager` |
| POST | `/bottles` | Store a bottle into an assigned locker | `CellarMember`, `CellarManager` |
| GET | `/bottles/{bottleId}` | Read a bottle | `CellarMember`, `CellarManager`, `Appraiser`, `InsuranceAgent`, `AuctionBroker` |
| GET | `/bottles` | List bottles | `CellarMember`, `CellarManager`, `Appraiser`, `InsuranceAgent`, `AuctionBroker` |
| POST | `/bottles/{bottleId}/provenance` | Set `provenance_status` | `CellarManager`, `Appraiser` |
| POST | `/appraisals` | Create a `DRAFT` appraisal | `Appraiser` |
| POST | `/appraisals/{appraisalId}/finalize` | `DRAFT` → `FINALIZED` (SoD + OCC) | `Appraiser` |
| GET | `/appraisals/{appraisalId}` | Read an appraisal | `CellarMember`, `CellarManager`, `Appraiser`, `InsuranceAgent`, `AuctionBroker` |
| GET | `/appraisals` | List appraisals | `CellarMember`, `CellarManager`, `Appraiser`, `InsuranceAgent`, `AuctionBroker` |
| POST | `/insurance-policies` | Quote a policy over covered bottles | `InsuranceAgent` |
| POST | `/insurance-policies/{policyId}/bind` | `QUOTED` → `BOUND`; debit premium | `InsuranceAgent` |
| POST | `/insurance-policies/{policyId}/cancel` | `QUOTED`/`BOUND` → `CANCELLED`; refund if bound | `InsuranceAgent` |
| GET | `/insurance-policies/{policyId}` | Read a policy | `CellarMember`, `CellarManager`, `InsuranceAgent` |
| GET | `/insurance-policies` | List policies | `CellarMember`, `CellarManager`, `InsuranceAgent` |
| POST | `/movement-requests` | Create an `INTAKE` or `WITHDRAWAL` request | `CellarMember` |
| POST | `/movement-requests/{movementRequestId}/approve` | `REQUESTED` → `APPROVED` | `CellarManager` |
| POST | `/movement-requests/{movementRequestId}/reject` | `REQUESTED` → `REJECTED` | `CellarManager` |
| POST | `/movement-requests/{movementRequestId}/complete` | `APPROVED` → `COMPLETED` | `CellarManager` |
| POST | `/movement-requests/{movementRequestId}/cancel` | `REQUESTED`/`APPROVED` → `CANCELLED` | `CellarMember`, `CellarManager` |
| GET | `/movement-requests/{movementRequestId}` | Read a movement request | `CellarMember`, `CellarManager` |
| GET | `/movement-requests` | List movement requests | `CellarMember`, `CellarManager` |
| POST | `/delivery-orders` | Schedule a delivery of withdrawn bottles | `CellarManager` |
| POST | `/delivery-orders/{deliveryOrderId}/deliver` | `SCHEDULED` → `DELIVERED` | `CellarManager` |
| POST | `/delivery-orders/{deliveryOrderId}/cancel` | `SCHEDULED` → `CANCELLED` | `CellarManager` |
| GET | `/delivery-orders/{deliveryOrderId}` | Read a delivery order | `CellarMember`, `CellarManager` |
| GET | `/delivery-orders` | List delivery orders | `CellarMember`, `CellarManager` |
| POST | `/consignments` | Open a `DRAFT` consignment for a bottle | `CellarMember` |
| POST | `/consignments/{consignmentId}/list` | `DRAFT` → `LISTED`; bottle → `CONSIGNED` | `AuctionBroker` |
| POST | `/consignments/{consignmentId}/offer` | `LISTED`/`COUNTERED` → `OFFERED` | `AuctionBroker` |
| POST | `/consignments/{consignmentId}/counter` | `OFFERED` → `COUNTERED` | `CellarMember` |
| POST | `/consignments/{consignmentId}/accept` | `OFFERED` → `ACCEPTED` (provisional proceeds) | `CellarMember` |
| POST | `/consignments/{consignmentId}/settle` | `ACCEPTED` → `SETTLED` (final proceeds, bottle sold) | `AuctionBroker` |
| POST | `/consignments/{consignmentId}/withdraw` | Non-terminal → `WITHDRAWN` | `CellarMember` |
| GET | `/consignments/{consignmentId}` | Read a consignment | `CellarMember`, `CellarManager`, `AuctionBroker` |
| GET | `/consignments` | List consignments | `CellarMember`, `CellarManager`, `AuctionBroker` |
| POST | `/waitlist-entries` | Join the waitlist | `CellarMember` |
| POST | `/waitlist-entries/{waitlistEntryId}/accept` | `OFFERED` → `FULFILLED`; claim locker | `CellarMember` |
| POST | `/waitlist-entries/{waitlistEntryId}/cancel` | `WAITING`/`OFFERED` → `CANCELLED` | `CellarMember` |
| GET | `/waitlist-entries/{waitlistEntryId}` | Read a waitlist entry | `CellarMember`, `CellarManager` |
| GET | `/waitlist-entries` | List waitlist entries | `CellarMember`, `CellarManager` |
| POST | `/maintenance-windows` | Schedule a maintenance window | `CellarManager` |
| POST | `/maintenance-windows/{maintenanceWindowId}/activate` | `SCHEDULED` → `ACTIVE`; locker → `MAINTENANCE` | `CellarManager` |
| POST | `/maintenance-windows/{maintenanceWindowId}/complete` | `ACTIVE` → `COMPLETED`; locker leaves maintenance | `CellarManager` |
| POST | `/maintenance-windows/{maintenanceWindowId}/cancel` | `SCHEDULED` → `CANCELLED` | `CellarManager` |
| GET | `/maintenance-windows/{maintenanceWindowId}` | Read a maintenance window | `CellarMember`, `CellarManager` |
| GET | `/maintenance-windows` | List maintenance windows | `CellarMember`, `CellarManager` |
| POST | `/climate-readings` | Record a climate reading (may set `BREACH`) | `CellarManager` |
| GET | `/climate-readings/{climateReadingId}` | Read a climate reading | `CellarMember`, `CellarManager` |
| GET | `/climate-readings` | List climate readings | `CellarMember`, `CellarManager` |
| POST | `/operations/cycle` | Advance the operations epoch (promote/expire/lapse) | `CellarManager` |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | `CellarManager` |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the Section 2 and Section 3 narratives; the table below records only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_BOTTLE_NOT_STORED` | 422 |
| `ERR_PROVENANCE_NOT_DOCUMENTED` | 422 |
| `ERR_DELIVERY_BOTTLE_NOT_WITHDRAWN` | 422 |
| `ERR_DRINK_WINDOW_NOT_OPEN` | 409 |
| `ERR_COURIER_SLOT_CONFLICT` | 409 |
| `ERR_MAINTENANCE_WINDOW_CONFLICT` | 409 |
| `ERR_LOCKER_CAPACITY_EXCEEDED` | 409 |
| `ERR_LOCKER_NOT_EMPTY` | 409 |
| `ERR_LOCKER_IN_MAINTENANCE` | 409 |
| `ERR_OFFER_BELOW_RESERVE` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 422 |
| `ERR_OUTSTANDING_BALANCE` | 422 |
| `ERR_MEMBER_HAS_ACTIVE_LOCKERS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BOTTLE_NOT_OWNED` | 422 |

