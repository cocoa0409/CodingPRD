# Restaurant Surplus Food Rescue API — Product Requirements Document

## 1. Introduction

Every evening, restaurants close with surplus food that is safe to eat but cannot be sold the next day. A food-rescue nonprofit sits in the middle of a delicate three-sided logistics problem: donor kitchens want a pickup to be fast, predictable, and tax-deductible; volunteer drivers donate their evenings and their vehicles; recipient agencies — shelters, pantries, community kitchens — can only accept what their refrigerators, freezers, and shelves can physically hold. When any link in that chain fails, the food spoils, the donor loses confidence, and the volunteer does not come back.

This document specifies the API that operates that network end to end. It governs how donor sites are onboarded and vetted, how surplus donation offers are published against a pickup window, how the platform assembles a rescue run by matching an eligible driver, a capacity-constrained agency, and enough cold-chain cooler inventory, how food-safety temperature readings are screened and adjudicated into compliance verdicts, and how failures are attributed through a strike system that can suspend donors and drivers. Because donors claim tax deductions on rescued food, the platform also maintains rate cards and issues substantiation receipts whose arithmetic is pinned to the cent.

Two technical commitments shape everything that follows. First, all time inside the system flows through a single logical clock rather than wall-clock time, so every expiry, cleaning hold, and timestamp validation is deterministic. Second, every scarce resource — agency capacity in pounds, vehicle capacity in pounds, cooler volume in liters, driver availability in hours — is accounted for as a quota that is reserved, committed, and released as runs move through their lifecycle. All resources are mounted under `/api`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing or empty, or the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the caller's role is not among the roles an endpoint admits, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `DispatchAdmin` — the nonprofit's operations staff. When `X-User-Role` is `DispatchAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `reporter_user_id` on a strike report filed by an admin, or as `adjudicated_by_user_id` on an adjudicated strike — but it never compares the value to any entity's `id`.
- `DonorCoordinator` — a restaurant donor representative. When `X-User-Role` is `DonorCoordinator`, `X-User-ID` is the `id` of the acting `DonorSite`; ownership checks on any resource that references a `DonorSite` compare the resource's donor foreign-key field to `X-User-ID`.
- `VolunteerDriver` — a volunteer driver. When `X-User-Role` is `VolunteerDriver`, `X-User-ID` is the `id` of the acting `VolunteerDriver`; ownership checks on any resource that references a `VolunteerDriver` compare the resource's driver foreign-key field to `X-User-ID`.
- `AgencyCoordinator` — a recipient agency's intake coordinator. When `X-User-Role` is `AgencyCoordinator`, `X-User-ID` is the `id` of the acting `RecipientAgency`; ownership checks on any resource that references a `RecipientAgency` compare the resource's agency foreign-key field to `X-User-ID`.

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

### 2.3. Pagination

List endpoints accept two query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are always sorted by `created_at` in ascending order. The `meta` block of a list response carries exactly four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. Several list endpoints additionally accept an optional `status` filter, and the rescue-run listing accepts optional `offer_id`, `agency_id`, and `driver_id` filters; the precise filter set per endpoint appears in §4 and in the relevant §3 narratives.

### 2.4. The Logical Clock and Lazy State Resolution

The platform keeps a single logical clock. Before anyone touches it, the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. Every timestamp validation, every lazy expiration, every cooler cleaning deadline, and every server-stamped `*_at` field reads this clock. A `DispatchAdmin`-only test-driving capability advances the clock to a supplied instant, passed as `to_iso8601`, and answers with the new current time.

Two state resolutions are lazy — they are not driven by timers but are recomputed whenever the entity is read or consulted for an eligibility decision, and advancing the logical clock triggers the same recomputation:

- A donation offer in `OPEN` or `MATCHED` whose `pickup_window_end` lies in the past transitions to `EXPIRED`. When the expiring offer was `MATCHED`, its current `PROPOSED` run is torn down to `CANCELLED` with the full release cascade — the booked window returns to `OPEN`, the cooler reservations flip to `RELEASED`, their coolers return from `RESERVED` to `AVAILABLE`, and the agency's committed capacity is released.
- A cooler in `CLEANING` or `QUARANTINED` whose `cleaning_ends_at` has been reached returns to `AVAILABLE`, and its `cleaning_ends_at` is cleared to null. A cooler leaving `QUARANTINED` additionally settles any linked reservation still holding in `QUARANTINED_HOLD` to `RETURNED`.

Both lazy resolutions run before any state-admissibility check on the affected resource, so a caller never sees a stale `OPEN` offer or a stale `CLEANING` cooler influence an error decision.

### 2.5. Common Resource Properties and Mutation Semantics

Unless noted otherwise, every resource carries four system properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that increments on every mutation of the resource and anchors the optimistic-concurrency rules of §2.6.

Temperature logs are the one exception to this contract: a temperature log carries only `id` and `created_at`. Both `updated_at` and `version` are absent from temperature logs, because a recorded reading is an immutable artifact and is never edited after creation.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and they are the only endpoints that take a version field:

- Dispatching a rescue run requires the request to carry `expected_offer_version`, holding the `version` of the target `DonationOffer` as the client last observed it. If the offer's current `version` has advanced past that value, the dispatch is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412). This guard exists because an offer can legitimately be `OPEN` again at a newer version — for instance after an earlier run was declined and the offer reverted from `MATCHED` back to `OPEN` — so no state precondition can catch the stale write; only the version comparison can.
- Issuing a tax receipt requires the request to carry `expected_donor_version`, holding the `version` of the `DonorSite` as the client last observed it. A mismatch with the donor's current `version` is rejected with `ERR_STALE_DONOR_VERSION` (HTTP 412). Issuing a receipt for a period that already has an `ISSUED` receipt legitimately supersedes that receipt under the amendment rule of §3.8, so again only the version check can reject a stale write.

No other endpoint accepts a version field.

### 2.7. Ownership Masking and Resource Addressing

Identifier existence is validated left to right along the URL path, and only after the path resolves are body-supplied foreign keys — `offer_id`, `driver_id`, `agency_id`, and each entry of `cooler_ids` — checked for existence. Each missing resource surfaces its own not-found error: `ERR_DONOR_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_COOLER_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, or `ERR_STRIKE_REPORT_NOT_FOUND`, all HTTP 404.

Ownership violations are deliberately masked as the same not-found errors rather than a distinct authorization failure. A `DonorCoordinator` may touch only its own donor record, its own offers, and its own tax receipts; addressing another donor's resources answers `ERR_DONOR_NOT_FOUND` or `ERR_OFFER_NOT_FOUND` as if the resource did not exist. A `VolunteerDriver` may touch only its own record, its own availability windows, and runs assigned to it; anything else answers `ERR_DRIVER_NOT_FOUND` or `ERR_RUN_NOT_FOUND`. An `AgencyCoordinator` may touch only its own agency record and runs targeting its agency; anything else answers `ERR_AGENCY_NOT_FOUND` or `ERR_RUN_NOT_FOUND`.

### 2.8. Validation Priority Order

When several checks could reject the same request, they fire in a fixed order so the surfaced error is deterministic. The order, highest priority first:

1. **Header context** — presence and validity of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the caller's role against the endpoint's admitted roles (`ERR_FORBIDDEN_ROLE`).
3. **Body well-formedness** — required fields present, no unknown fields, correct types, valid enum members, positive integers where noted, `window_end` after `window_start`, pickup window length within the permitted band, `pickup_time` and `arrival_time` not after the logical clock, `arrival_time` not before `pickup_time`, the attestation flag affirmed, disposal documentation present when the reason demands it, fault-party and reason consistent, `cooler_ids` absent on non-cold-chain work, and tax periods ordered and not extending past the logical clock (`ERR_INVALID_REQUEST`).
4. **Existence** — path identifiers left to right, then body foreign keys (the resource-specific 404 family of §2.7).
5. **Ownership masking** — entity-backed callers confined to their own resources (the same 404 family).
6. **State admissibility** — the target resource's lifecycle must admit the operation, including cross-entity state preconditions such as an active donor at publish time or an active driver at window declaration or pinned dispatch (`ERR_INVALID_STATE_TRANSITION`, `ERR_DONOR_NOT_ACTIVE`, `ERR_DRIVER_NOT_ACTIVE`, `ERR_OFFER_NOT_OPEN`, `ERR_RUN_NOT_IN_EXPECTED_STATE`, `ERR_STRIKE_NOT_FILED`, `ERR_PICKUP_WINDOW_PAST`). The lazy resolutions of §2.4 run before this tier.
7. **Optimistic concurrency** — the expected-version fields of §2.6 (`ERR_STALE_OFFER_VERSION`, `ERR_STALE_DONOR_VERSION`).
8. **Cold-chain safety** — certification, the pickup kill screen, and the delivery danger-zone verdict (`ERR_DRIVER_NOT_COLD_CHAIN_CERTIFIED`, `ERR_SAFETY_VIOLATION_AT_PICKUP`, `ERR_SAFETY_VERDICT_VIOLATION`).
9. **Temporal interval rules** — availability-window overlap, driver window coverage, cooler buffered-interval conflicts, and rate-card window overlap (`ERR_AVAILABILITY_WINDOW_OVERLAP`, `ERR_DRIVER_WINDOW_MISSING`, `ERR_COOLER_UNAVAILABLE`, `ERR_RATE_CARD_WINDOW_OVERLAP`).
10. **Category acceptability** — a pinned agency must accept the offer's food category (`ERR_AGENCY_CATEGORY_NOT_ACCEPTED`).
11. **Capacity quotas** — vehicle capacity, agency committed-versus-capacity, cooler liters within slot limits, delivery overage, and the two fiscal gates on receipts (`ERR_DRIVER_CAPACITY_EXCEEDED`, `ERR_AGENCY_CAPACITY_EXCEEDED`, `ERR_INSUFFICIENT_COOLER_CAPACITY`, `ERR_DELIVERY_OVERAGE_EXCEEDED`, `ERR_RECEIPT_NO_VERIFIED_RESCUES`, `ERR_NO_RATE_CARD_EFFECTIVE`). Within receipt issuance the verified-run set is evaluated first and rate-card coverage second, as §3.8 details.
12. **Selector fallback** — when a resource class was omitted at dispatch and its eligibility pool is empty, the first empty pool in resolution order is reported: driver (`ERR_NO_ELIGIBLE_DRIVER`), then agency (`ERR_NO_ELIGIBLE_AGENCY`), then coolers (`ERR_INSUFFICIENT_COOLER_CAPACITY`).

### 2.9. Units, Precision, and Rounding

Weights are whole pounds, carried as integers; no fractional pounds exist anywhere in the system. Money is integer cents; receipt arithmetic never produces a fraction of a cent. Temperatures are recorded in Fahrenheit with one decimal place. Durations and deadlines are expressed in whole minutes.

Where a rule rounds, the method is stated with the rule: the per-pound enhanced tax rate rounds half-up to a whole cent, cooler volume requirements and the delivery-overage ceiling round up to the next whole unit. Threshold inclusivity is always explicit — a boundary written as "inclusive" admits equality.

## 3. Business Logic & Workflows

### 3.1. Building the Rescue Network: Donors, Agencies, Drivers, and Coolers

A `DispatchAdmin` onboards a donor site by supplying its `legal_name`, its `ein` — the nine-digit IRS employer identification number that later anchors tax substantiation — and a `contact_email`. The optional `enhanced_deduction_eligible` flag defaults to false and, when set, switches the donor's receipts to the enhanced-deduction valuation variant of §3.8. A new donor enters `PENDING_REVIEW` with `strike_count` and all weight and tax aggregates at zero. Lifecycle changes are requested by submitting a `target_status` on the donor's status resource. Approval moves the donor from `PENDING_REVIEW` to `ACTIVE` (any other source state is rejected with `ERR_INVALID_STATE_TRANSITION`) and increments the donor's `version`. Suspension moves an `ACTIVE` donor to `SUSPENDED`; reinstatement moves a `SUSPENDED` donor back to `ACTIVE` and resets `strike_count` to zero. Deactivation is terminal: a donor reaches `DEACTIVATED` from either `ACTIVE` or `SUSPENDED` only when none of its offers remains in `DRAFT`, `OPEN`, `MATCHED`, `SCHEDULED`, `PICKED_UP`, or `DELIVERED`, and the attempt is otherwise rejected with `ERR_INVALID_STATE_TRANSITION`. Suspending a donor also tears down its book of business, a cascade detailed alongside strikes in §3.6.

Registering a recipient agency takes a display `name`, a non-empty `accepts_categories` list drawn from `COLD_HELD`, `HOT_HELD`, `PRODUCE`, and `SHELF_STABLE`, and four per-category capacity ceilings: `capacity_cold_held_lbs`, `capacity_hot_held_lbs`, `capacity_produce_lbs`, and `capacity_shelf_stable_lbs`. The agency's four committed counters — `committed_cold_held_lbs`, `committed_hot_held_lbs`, `committed_produce_lbs`, `committed_shelf_stable_lbs` — and its `received_total_lbs` all start at zero and evolve per the capacity accounting of §3.7.

Volunteer drivers join through a `DispatchAdmin` as well, registered with a `full_name`, an `email`, the vehicle's `vehicle_capacity_lbs`, the vehicle's `cooler_slot_count` (zero or more), and an optional `cold_chain_certified` flag defaulting to false. A new driver enters `ONBOARDING` with `reliability_score` 100 and `completed_run_count` and `upheld_strike_count` at zero. Driver lifecycle changes likewise take a `target_status`: activation moves a driver from `ONBOARDING` to `ACTIVE` (otherwise `ERR_INVALID_STATE_TRANSITION`); suspension and reinstatement mirror the donor lifecycle, with reinstatement resetting `reliability_score` to 80 and suspension triggering the run-teardown cascade of §3.6.

Once `ACTIVE`, a driver declares when the vehicle is free by creating availability windows on their own record, supplying `window_start` (inclusive) and `window_end` (exclusive, and required to be after `window_start`). An `ONBOARDING` or `SUSPENDED` driver attempting this is rejected with `ERR_DRIVER_NOT_ACTIVE`. A new window must not overlap any of the same driver's existing windows in `OPEN` or `BOOKED` status: two intervals conflict when the new start falls before the existing end and the existing start falls before the new end, with half-open semantics so a new window starting exactly when an existing one ends is allowed — no buffer is appended, in deliberate contrast to the cooler intervals of §3.3. An overlap is rejected with `ERR_AVAILABILITY_WINDOW_OVERLAP`. A window starts `OPEN` with `booked_run_id` null; dispatch books it, and it returns to `OPEN` with `booked_run_id` cleared as soon as the booking run reaches `DECLINED`, `FAILED_PICKUP`, `FAILED_DELIVERY`, `CANCELLED`, or `VERIFIED`. Drivers can review their own windows (and admins can review any driver's) through the window listing on the driver resource, with its optional `status` filter; the window's `driver_id` names its owner.

Cold-chain inventory is managed as coolers, each created with a human `label` and a `capacity_liters` volume that must be greater than zero, entering `AVAILABLE`. A cooler's `status` walks a cycle — `AVAILABLE` to `RESERVED` at dispatch, to `CHECKED_OUT` at pickup, then either to `CLEANING` on an ordinary return or to `QUARANTINED` after a safety disposal — and both holding states carry a `cleaning_ends_at` deadline: 45 minutes after the return clock reading for `CLEANING`, 240 minutes after it for `QUARANTINED`. As §2.4 states, these resolve back to `AVAILABLE` lazily. Cooler reservations are created only by the system: each records its `cooler_id`, the `rescue_run_id` it serves, and a blocked interval whose `blocked_start` is the offer's `pickup_window_start` at dispatch time and whose `blocked_end` is the offer's `pickup_window_end` plus 135 minutes — a 90-minute return allowance followed by a 45-minute cleaning buffer. A reservation's own `status` moves from `RESERVED` to `CHECKED_OUT` at pickup, to `RETURNED` on an ordinary return, to `QUARANTINED_HOLD` when its cooler is quarantined (and lazily from `QUARANTINED_HOLD` to `RETURNED` when the cooler clears), or directly to `RELEASED` when its run dies before pickup — that is, when the reserving run reaches `DECLINED`, `FAILED_PICKUP`, or `CANCELLED`. `RELEASED` and `RETURNED` are terminal. Both a cooler's reservation history and a run's reservation set are readable as listings with the usual `status` filter.

### 3.2. Donation Offers: Drafting, Publishing, and the Re-Offer Loop

A donation offer is born when a `DonorCoordinator` describes a surplus batch: the owning `donor_site_id` (which must equal the caller's `X-User-ID`), the `food_category` (`COLD_HELD`, `HOT_HELD`, `PRODUCE`, or `SHELF_STABLE`), the donor's `estimated_weight_lbs` as a positive whole number, and the `pickup_window_start` (inclusive) and `pickup_window_end` (exclusive). The window's length must be at least 30 minutes and no more than 240 minutes — four hours. The server derives `requires_cold_chain` itself: it is true exactly when the category is `COLD_HELD` or `HOT_HELD`, and any client-supplied value for it is ignored. The offer lands in `DRAFT` with `failed_attempts` at zero and `current_run_id` null.

Publishing and cancelling both ride the offer's status resource with a `target_status` naming the destination. Publishing moves an offer from `DRAFT` to `OPEN`, performed by the owning `DonorCoordinator` or a `DispatchAdmin`, and carries three preconditions: the offer must currently be `DRAFT` (else `ERR_INVALID_STATE_TRANSITION`), the donor site must be `ACTIVE` (else `ERR_DONOR_NOT_ACTIVE`), and `pickup_window_end` must still lie after the current logical clock (else `ERR_PICKUP_WINDOW_PAST`). Cancellation is the donor's or an admin's escape hatch with sharply different consequences by stage. From `DRAFT` or `OPEN`, cancelling is free — no run exists and nothing unwinds. From `MATCHED` or `SCHEDULED`, cancelling tears the current run down to `CANCELLED`: the agency's commitment is released, the booked window returns from `BOOKED` to `OPEN`, cooler reservations flip to `RELEASED`, and their coolers return from `RESERVED` to `AVAILABLE`. When the cancelling actor is a `DonorCoordinator`, that teardown additionally auto-files a strike report against the donor — `subject_type` `DONOR_SITE` with `reporter_role` `SYSTEM` — because a donor cancelling a committed rescue strands a driver and an agency; an admin-initiated cancel files no strike. Offers already `PICKED_UP` or `DELIVERED` are in flight and cannot be cancelled through this path at all.

The heart of the offer lifecycle is the re-offer loop. Dispatch moves `OPEN` to `MATCHED` and stamps `current_run_id` with the new run. If the assigned driver declines, the offer reverts from `MATCHED` to `OPEN` with `failed_attempts` unchanged, ready to be dispatched again. Once the driver accepts, the offer advances from `MATCHED` to `SCHEDULED`; a successful pickup moves it to `PICKED_UP`; a recorded delivery moves it to `DELIVERED`; and the agency's countersignature closes it from `DELIVERED` to `CLOSED`. A pickup-stage failure instead sends the offer back around: `failed_attempts` increments by one, and the offer returns from `SCHEDULED` to `OPEN` — unless that increment reaches three, in which case the offer goes to `EXPIRED` with `failed_attempts` set to 3 and can never be re-offered. A delivery-stage failure moves a `PICKED_UP` offer to `DISCARDED`. Independently of all of this, the lazy expiry of §2.4 can move an `OPEN` or `MATCHED` offer to `EXPIRED` once its window passes. `CLOSED`, `CANCELLED`, `EXPIRED`, and `DISCARDED` are the terminal states. Donors and admins read offers directly or as a per-donor listing with its optional `status` filter, and the runs behind an offer are discoverable through the run listing filtered by `offer_id` rather than through any nested expansion of `current_run_id`.

### 3.3. Dispatch: Assembling a Rescue Run

Dispatch is the platform's central act: a `DispatchAdmin` commits a driver, an agency, and cold-chain equipment to one offer in a single optimistic-concurrency-guarded write. The request names the `offer_id` and must carry `expected_offer_version` per §2.6; a stale version answers `ERR_STALE_OFFER_VERSION` before anything else is attempted, and an offer that is not `OPEN` — after the lazy expiry of §2.4 has had its say — answers `ERR_OFFER_NOT_OPEN`. Three selector classes may each be pinned by the request or left to the platform: `driver_id`, `agency_id`, and `cooler_ids`.

When `driver_id` is omitted, the driver selector screens every registered driver for eligibility: the driver must be `ACTIVE`; must hold `cold_chain_certified` when the offer's `requires_cold_chain` is true; must present `vehicle_capacity_lbs` at least equal to the offer's `estimated_weight_lbs`; and must own an `OPEN` availability window that fully covers the pickup window, meaning `window_start` on or before `pickup_window_start` and `window_end` on or after `pickup_window_end`. Eligible drivers are ranked by `reliability_score` descending, then by the covering window's `window_start` ascending, then by that window's `created_at` ascending — identifiers never participate in ranking. The window used for ranking is the driver's earliest-starting covering `OPEN` window, ties broken by earliest `created_at`, and that is the window the booking marks `BOOKED`. An empty driver pool is reported as `ERR_NO_ELIGIBLE_DRIVER`. When `driver_id` is pinned instead, each eligibility rule surfaces as its own error: a driver not `ACTIVE` answers `ERR_DRIVER_NOT_ACTIVE`, a missing cold-chain certificate on a cold-chain offer answers `ERR_DRIVER_NOT_COLD_CHAIN_CERTIFIED`, insufficient vehicle capacity answers `ERR_DRIVER_CAPACITY_EXCEEDED`, and the absence of a covering `OPEN` window answers `ERR_DRIVER_WINDOW_MISSING`.

When `agency_id` is omitted, the agency selector admits agencies whose `accepts_categories` contains the offer's `food_category` and whose committed load for that category plus the offer's `estimated_weight_lbs` does not exceed the matching capacity ceiling — the boundary is inclusive, so exactly filling a category is allowed. Ranking is best fit: the agency whose remaining slack after this offer — capacity minus committed minus estimated — is smallest comes first, ties broken by the agency's `created_at` ascending. An empty agency pool answers `ERR_NO_ELIGIBLE_AGENCY`. A pinned agency that does not accept the category is rejected with `ERR_AGENCY_CATEGORY_NOT_ACCEPTED`, and one whose capacity would be exceeded answers `ERR_AGENCY_CAPACITY_EXCEEDED`. When several selector classes are omitted at once and more than one pool is empty, only the first in resolution order is reported — driver, then agency, then coolers.

Coolers are needed only for cold-chain offers. The requirement is the offer's `estimated_weight_lbs` scaled by half a liter per pound and rounded up to a whole liter. A cooler is a candidate when, after the lazy resolution of §2.4, its status is not `CLEANING`, `QUARANTINED`, or `CHECKED_OUT` and none of that cooler's own reservations in `RESERVED` or `CHECKED_OUT` has a buffered blocked interval overlapping the new one — the interval test does the real work, so a cooler still `RESERVED` from an earlier dispatch remains a candidate for a new run whose blocked interval does not overlap the existing reservation's. Intervals conflict when the new start falls before the existing `blocked_end` and the existing `blocked_start` falls before the new end, and because the test is strict, a new interval starting exactly at an existing `blocked_end` is allowed. In auto mode — `cooler_ids` omitted — candidates are sorted by `capacity_liters` descending with ties broken by `created_at` ascending, and accumulated in that order while the running total remains below the required liters and the selection count remains below the assigned driver's `cooler_slot_count`; if the accumulated total cannot reach the requirement within the slot limit, dispatch fails with `ERR_INSUFFICIENT_COOLER_CAPACITY`. In pinned mode, every listed cooler must be a candidate under that same test — a cooler in `CLEANING`, `QUARANTINED`, or `CHECKED_OUT`, or one whose own `RESERVED` or `CHECKED_OUT` reservation's buffered interval conflicts, answers `ERR_COOLER_UNAVAILABLE` — and the pinned set must fit within the driver's `cooler_slot_count` while summing to at least the required liters, else `ERR_INSUFFICIENT_COOLER_CAPACITY`. For non-cold-chain offers, `cooler_ids` must be omitted or empty (anything else is `ERR_INVALID_REQUEST`) and no reservation is created at all.

A successful dispatch lands a bundle of effects as one atomic act. The offer moves from `OPEN` to `MATCHED`, its `version` increments by one, and `current_run_id` is set to the new run. The new run is born `PROPOSED` with `safety_status` `UNVERIFIED`, its `estimated_weight_snapshot` pinned from the offer's current estimate — this snapshot, not any later edit of the offer, drives all subsequent capacity and overage math. Everything the run will later record starts null: `actual_weight_lbs`, `pickup_time`, `arrival_time`, `verified_at`, `driver_attestation_signed_at`, `agency_countersigned_by_user_id`, `agency_countersigned_at`, `fault_party`, `failure_reason`, `disposal_method`, and `disposal_notes` all stay null until the lifecycle act that records them. The selected window goes from `OPEN` to `BOOKED` with `booked_run_id` pointing at the run. Each selected cooler stands at `RESERVED` under a fresh `RESERVED` reservation carrying the buffered blocked interval — a cooler that was `AVAILABLE` moves to `RESERVED`, and one already `RESERVED` from a non-overlapping earlier dispatch simply remains `RESERVED`. And the agency's committed counter for the offer's category rises by the snapshot weight, reserving capacity per the accounting of §3.7. The donor's `pending_estimated_lbs` rises by the same estimate at the same moment.

### 3.4. The Driver's Run: Respond, Pickup, Deliver

Only the assigned driver may act on a run at the driving stages, and only the destination agency's coordinator may countersign it; anyone else addressing the run is masked out with `ERR_RUN_NOT_FOUND` as §2.7 describes. A run also carries two independent status dimensions that must never be conflated: `run_status` tracks the logistics (`PROPOSED`, `CONFIRMED`, `PICKED_UP`, `DELIVERED`, `VERIFIED`, `DECLINED`, `FAILED_PICKUP`, `FAILED_DELIVERY`, `CANCELLED` — the last five terminal), while `safety_status` tracks the food-safety verdict (`UNVERIFIED`, `PROVISIONAL_COMPLIANT`, `VERIFIED_COMPLIANT`, `VERIFIED_VIOLATION`). A run can be `FAILED_DELIVERY` with `safety_status` `VERIFIED_VIOLATION`; the dimensions evolve independently.

The run begins `PROPOSED`, waiting on the driver's answer. Responding with `decision` `ACCEPT` requires the run to still be `PROPOSED` — any other state answers `ERR_RUN_NOT_IN_EXPECTED_STATE`. There is deliberately no fresh driver-status check at this moment: if the driver was suspended between dispatch and response, the suspension cascade of §3.6 already tore the proposed run down, so the state check is what fires. Acceptance moves the run to `CONFIRMED` and the offer from `MATCHED` to `SCHEDULED`, and it re-verifies the agency's capacity gate — by now the run itself is already inside the committed set, so the re-check asks that the committed total not exceed the category capacity, with equality allowed, and a breach answers `ERR_AGENCY_CAPACITY_EXCEEDED`. Responding `DECLINE` from `PROPOSED` moves the run to `DECLINED` and unwinds everything dispatch reserved: the offer reverts from `MATCHED` to `OPEN`, the window returns to `OPEN`, the reservations flip to `RELEASED`, their coolers return to `AVAILABLE`, and the agency's commitment is released.

Pickup is recorded by the assigned driver on a `CONFIRMED` run — otherwise `ERR_RUN_NOT_IN_EXPECTED_STATE` — and bundles three inputs: the `pickup_time`, which must not lie after the current logical clock; the `attestation_confirmed` flag, which must be true because it is the Good-Samaritan liability attestation, its absence answering `ERR_INVALID_REQUEST`; and, for cold-chain offers only, the `pickup_temp_f` reading, which must survive the kill screen of §3.5 or the pickup is refused with `ERR_SAFETY_VIOLATION_AT_PICKUP`. Success stamps `pickup_time`, sets `driver_attestation_signed_at` to the logical clock, writes a temperature log whose `point` is `PICKUP`, flips `safety_status` to `PROVISIONAL_COMPLIANT`, moves the reservations and their coolers from `RESERVED` to `CHECKED_OUT`, and advances both run and offer to `PICKED_UP`.

Delivery is recorded by the assigned driver on a `PICKED_UP` run with three inputs: `arrival_time`, which must sit on or after `pickup_time` and on or before the current logical clock; the agency-scale `actual_weight_lbs`; and, for cold-chain offers, the `arrival_temp_f` reading that completes the danger-zone verdict of §3.5. The weight must be at least one pound and no more than the `estimated_weight_snapshot` scaled by five-quarters and rounded up to a whole pound — exactly hitting that ceiling is allowed, and exceeding it is rejected with `ERR_DELIVERY_OVERAGE_EXCEEDED`. A cold-chain verdict of violation rejects the delivery with `ERR_SAFETY_VERDICT_VIOLATION`, persists `safety_status` as `VERIFIED_VIOLATION`, and leaves the run in `PICKED_UP` so the failure path can take over. A clean delivery stamps `arrival_time` and `actual_weight_lbs`, writes a temperature log whose `point` is `ARRIVAL`, sets `safety_status` to `VERIFIED_COMPLIANT` — non-cold-chain offers are always compliant — releases the agency's commitment by the snapshot weight while adding the actual weight to its received total, settles the reservations to `RETURNED` and sends their coolers to `CLEANING` with `cleaning_ends_at` 45 minutes out, and advances both run and offer to `DELIVERED`.

### 3.5. Cold-Chain Safety: Temperature Screening and the Danger-Zone Verdict

Food-safety protocol applies only to cold-chain offers — those whose `food_category` is `COLD_HELD` or `HOT_HELD`. `PRODUCE` and `SHELF_STABLE` runs are always treated as compliant, and while their pickup and arrival logs still document the run, no threshold is ever applied to them.

Two danger predicates define the safe band, one per cold-chain category. A `COLD_HELD` reading is dangerous when its temperature rises above 41.0°F. A `HOT_HELD` reading is dangerous when its temperature falls below 135.0°F. Note both predicates are strict — exactly 41.0°F and exactly 135.0°F are not dangerous.

The provisional verdict runs at pickup and screens only the kill temperature, never elapsed time. For `COLD_HELD` food, a pickup reading at or above 70.0°F trips the screen; for `HOT_HELD` food, a reading at or below 100.0°F trips it. A tripped screen rejects the pickup outright with `ERR_SAFETY_VIOLATION_AT_PICKUP`; a clean screen is what permits `safety_status` to become `PROVISIONAL_COMPLIANT`.

The final verdict runs at delivery and considers exactly two logs for the run, ordered by `recorded_at`: the `PICKUP` log — time t₀, temperature T₀ — and the `ARRIVAL` log — time t₁, temperature T₁. Let the span be the elapsed minutes from t₀ to t₁. The cumulative danger minutes are computed by linear interpolation against the category's danger threshold K (41.0 for `COLD_HELD`, 135.0 for `HOT_HELD`): zero when neither reading is dangerous; the whole span when both are dangerous; when only the arrival reading is dangerous, the span multiplied by the difference between T₁ and K and divided by the difference between T₁ and T₀; and when only the pickup reading is dangerous, the span multiplied by the difference between K and T₀ and divided by the difference between T₁ and T₀. The verdict is `COMPLIANT` when the danger minutes total no more than 240 — four hours — and the boundary is inclusive: exactly 240 is compliant, 241 is a violation. A violation rejects the delivery with `ERR_SAFETY_VERDICT_VIOLATION` and persists `VERIFIED_VIOLATION` on the run.

Every temperature log records the `rescue_run_id` it belongs to, its `point` (`PICKUP` from record-pickup, `ARRIVAL` from a record-delivery attempt), the `temp_f` reading, a `recorded_at` equal to `pickup_time` for pickup logs and to `arrival_time` for arrival logs, and the `recorded_by_user_id` of the caller. A run's logs are listable by the assigned driver, the destination agency's coordinator, and admins.

### 3.6. Failures, Fault Attribution, and Strikes

Runs fail in two stages with different rulebooks, and the failing call always names a `fault_party` — `DONOR`, `DRIVER`, `AGENCY`, or `NONE` — and a `reason`, one of `DONOR_NO_SHOW`, `DRIVER_NO_SHOW`, `SAFETY_REJECTED`, `AGENCY_CLOSED`, `OVER_CAPACITY`, `SAFETY_DISPOSAL`, or `OTHER`, which lands on the run as its `failure_reason`.

From `CONFIRMED`, the pickup-stage rulebook applies (a run in any other state answers `ERR_RUN_NOT_IN_EXPECTED_STATE`). The fault and reason must agree: `SAFETY_REJECTED` requires `fault_party` `NONE`, `DONOR_NO_SHOW` requires `DONOR`, and `DRIVER_NO_SHOW` requires `DRIVER` — mismatches are `ERR_INVALID_REQUEST`. Every pickup-stage failure releases the agency's commitment, returns the window to `OPEN`, releases the reservations, and frees their coolers to `AVAILABLE`. What happens to the offer depends on the reason: a `SAFETY_REJECTED` failure discards the food but blames no one, moving the offer from `SCHEDULED` to `DISCARDED` and filing no strike; any other reason increments the offer's `failed_attempts` by one and sends it back to `OPEN`, or to `EXPIRED` when the increment reaches three. When `fault_party` is `DONOR` or `DRIVER`, a strike report is auto-filed against the corresponding subject, with `reporter_role` set to `DRIVER` when the assigned driver made the call, `ADMIN` when a `DispatchAdmin` did, and `SYSTEM` when a cascade did.

From `PICKED_UP`, the delivery-stage rulebook applies. `SAFETY_DISPOSAL` is the signature reason here: it is admissible only when the run's `safety_status` is already `VERIFIED_VIOLATION` — otherwise `ERR_RUN_NOT_IN_EXPECTED_STATE` — and it demands non-empty `disposal_method` and `disposal_notes` documenting the destruction, with `fault_party` fixed at `NONE`. `AGENCY_CLOSED` and `OVER_CAPACITY` instead require `fault_party` `AGENCY`. Every delivery-stage failure releases the agency's commitment (its received total is untouched), returns the window to `OPEN`, and moves the offer from `PICKED_UP` to `DISCARDED`. Equipment fate splits on the reason: a `SAFETY_DISPOSAL` holds the reservations in `QUARANTINED_HOLD` and quarantines their coolers with `cleaning_ends_at` 240 minutes — four hours — past the failure clock, while any other reason returns the reservations to `RETURNED` and sends the coolers to the ordinary 45-minute `CLEANING`. Because strike reports exist to discipline donors and drivers, a delivery-stage failure with `fault_party` `AGENCY` files no strike at all.

Strike reports are also born from two cascades already mentioned: a donor cancelling a `MATCHED` or `SCHEDULED` offer (§3.2) and a suspended driver's confirmed runs (below). Each report records the `rescue_run_id` whose failure filed it, the `reporter_role` (`DRIVER`, `ADMIN`, or `SYSTEM`, with `reporter_user_id` null exactly when `SYSTEM`), the polymorphic subject — `subject_type` `DONOR_SITE` or `DRIVER`, with `subject_id` naming a donor site or a volunteer driver accordingly — and the `reason` copied from the failing call. A report opens `FILED` with `adjudicated_by_user_id` and `adjudicated_at` null, and a run's reports are listable by admins.

Adjudication is a `DispatchAdmin`'s act with a segregation-of-duties guard: the report must still be `FILED` (else `ERR_STRIKE_NOT_FILED`), and when `reporter_role` is anything other than `SYSTEM`, the adjudicator's `X-User-ID` must differ from `reporter_user_id` — a reporter may not judge their own accusation, and the attempt answers `ERR_SELF_ADJUDICATION_FORBIDDEN`. The `outcome` decides the penalty. `WAIVED` changes nothing about the subject and simply closes the report. `UPHELD` stamps `adjudicated_by_user_id` and `adjudicated_at`, then punishes by subject type. Against a donor site, `strike_count` increments by one, and the third upheld strike — the boundary is inclusive — suspends the donor. Against a driver, `upheld_strike_count` increments by one and `reliability_score` drops by 50, floored at zero; if the score then falls strictly below 60 the driver is suspended, so a driver sitting at exactly 60 remains `ACTIVE`.

Both suspensions cascade immediately. A suspended donor sees every one of its offers in `DRAFT` or `OPEN` cancelled outright with no strike, and every offer in `MATCHED` or `SCHEDULED` cancelled with its current run torn down to `CANCELLED` — window released, reservations released, coolers freed, agency commitment released — while offers already `PICKED_UP` or `DELIVERED` are in flight and untouched. A suspended driver sees each of their `PROPOSED` runs moved to `DECLINED` with the full release cascade and the offer reverted from `MATCHED` to `OPEN`, and each of their `CONFIRMED` runs moved to `FAILED_PICKUP` with `fault_party` `DRIVER` and `reason` `DRIVER_NO_SHOW`: the agency commitment releases, the offer's `failed_attempts` increments and it returns to `OPEN` or expires on the third strike under the three-failures rule, and a `SYSTEM`-reported strike is auto-filed against the driver. Runs already `PICKED_UP` or `DELIVERED` are again untouched. Reinstatement paths restore donors with `strike_count` zeroed and drivers with `reliability_score` reset to 80, as §3.1 states.

### 3.7. Countersignature, Impact Accounting, and Capacity Bookkeeping

The rescue formally closes when the destination agency's own `AgencyCoordinator` countersigns a `DELIVERED` run — any other state answers `ERR_RUN_NOT_IN_EXPECTED_STATE`, and any other caller is masked out per §2.7. Countersigning is the liability-documentation act: it stamps `verified_at` with the logical clock and records the caller in `agency_countersigned_by_user_id` alongside `agency_countersigned_at`, moves the run to `VERIFIED`, moves the offer from `DELIVERED` to `CLOSED`, and releases the booked window back to `OPEN`. That single act also settles three ledgers at once.

The donor's impact ledger switches from estimate to verified weight. While any of a donor's offers sits in `MATCHED`, `SCHEDULED`, `PICKED_UP`, or `DELIVERED`, its `pending_estimated_lbs` carries the sum of those offers' `estimated_weight_lbs` — the donor's self-report. At countersignature the estimate leaves `pending_estimated_lbs` and the run's agency-scale `actual_weight_lbs` enters `lifetime_weight_lbs`, so the verified total is the sum of actual weights over the donor's `VERIFIED` runs. The two variants diverge exactly when a scale reading disagrees with a donor estimate.

The driver's reliability ledger rewards completion: `completed_run_count` increments by one and `reliability_score` rises by 5, capped at 100. Combined with the strike penalties of §3.6, a driver's score starts at 100, gains up to 5 per verified rescue, loses 50 per upheld strike with a floor of zero, suspends the driver only when it falls strictly below 60, and resets to 80 on reinstatement.

The agency's capacity ledger is the quota every other section references. For an agency and a category, the committed load is the sum of `estimated_weight_snapshot` over runs targeting that agency in `PROPOSED`, `CONFIRMED`, or `PICKED_UP` whose offer belongs to that category — this is precisely the `committed_cold_held_lbs`, `committed_hot_held_lbs`, `committed_produce_lbs`, and `committed_shelf_stable_lbs` family. Dispatch reserves by adding the snapshot to that committed set, and the capacity gate — committed plus the new estimate no greater than the ceiling, equality allowed — is evaluated both at dispatch and again at acceptance, where the run's own snapshot is already inside the committed total. Recording a delivery releases the commitment (committed falls by the snapshot) and simultaneously converts it into impact: `received_total_lbs` rises by the actual weight, which is the sum of actual weights over runs that reached `DELIVERED` or `VERIFIED` for the agency. Declines, failures, and cancellations release the commitment without touching received totals.

### 3.8. Tax Substantiation: Rate Cards and Receipts

Tax valuation begins with rate cards. A `DispatchAdmin` publishes a card with an effective window — `effective_start` inclusive and `effective_end` exclusive, the end strictly after the start — and eight per-pound cent rates pairing a fair-market value with a cost basis for each category: `cold_held_fmv_cents_per_lb` with `cold_held_basis_cents_per_lb`, `hot_held_fmv_cents_per_lb` with `hot_held_basis_cents_per_lb`, `produce_fmv_cents_per_lb` with `produce_basis_cents_per_lb`, and `shelf_stable_fmv_cents_per_lb` with `shelf_stable_basis_cents_per_lb`. A new card's window must not overlap any existing card's window, with half-open adjacency allowed — a card starting exactly when another ends coexists with it — and an overlap is rejected with `ERR_RATE_CARD_WINDOW_OVERLAP`. Successful creations assign `card_version` monotonically starting at 1, in creation order; rejected creations never consume a version.

A `DispatchAdmin` issues a donor's receipt by naming the `period_start` (inclusive) and `period_end` (exclusive) and carrying `expected_donor_version` per §2.6. The period must be ordered — start strictly before end — and `period_end` must not lie after the current logical clock, else `ERR_INVALID_REQUEST`. Two fiscal gates then fire in a fixed sequence: the verified-run set first, rate-card coverage second. A run contributes exactly when it is `VERIFIED`, belongs to this donor, and its `verified_at` falls on or after `period_start` and strictly before `period_end`; if that set is empty the issuance stops with `ERR_RECEIPT_NO_VERIFIED_RESCUES`. Runs still `DELIVERED` but not yet countersigned never contribute. Next, the unique rate card whose window contains `period_end` — `effective_start` on or before it, `effective_end` strictly after — must exist, else `ERR_NO_RATE_CARD_EFFECTIVE`.

The receipt's arithmetic groups the contributing runs by their offer's `food_category`, producing one entry per category present in the `lines` array, each carrying its `food_category`, `weight_lbs`, `fmv_cents_per_lb`, `basis_cents_per_lb`, `standard_cents`, and `enhanced_cents`. A line's `weight_lbs` is the sum of `actual_weight_lbs` over the category's runs. Its standard value, `standard_cents`, is that weight multiplied by the card's fair-market-value rate for the category. Its enhanced per-pound rate is the smaller of two quantities: twice the basis rate, or the basis rate plus one-half of the excess of the fair-market-value rate over the basis rate — and that half-excess is rounded half-up to a whole cent before being added. The rounding order is pinned: the per-pound enhanced rate is fully settled, including its half-up rounding, before it is multiplied by the line's weight to produce `enhanced_cents`; rounding the line total after multiplication is a different number and is not permitted. For example, at a fair-market value of 151 cents and a basis of 100 cents, the enhanced per-pound rate is 126 cents — the half-excess of 25.5 rounds half-up to 26, well under the doubling cap of 200 — so a ten-pound line is worth 1260 cents, not the 1255 that rounding after multiplication would yield. Because the enhanced rate never exceeds the fair-market value, the enhanced variant is always at most the standard variant for identical data.

Totals roll the lines up: `total_weight_lbs` sums the line weights, `total_standard_value_cents` sums the standard values, and `total_enhanced_value_cents` sums the enhanced values. The receipt's `deductible_value_cents` is the enhanced total when the donor's `enhanced_deduction_eligible` flag is set, and the standard total otherwise. Issuance stamps `issued_at` with the logical clock, pins `rate_card_version` to the version of the card whose window contained the period end, and marks the receipt `ISSUED`.

Receipts amend rather than delete. Issuing a new receipt for the same donor with identical `period_start` and `period_end` supersedes the previously `ISSUED` receipt, which becomes `AMENDED`; an `AMENDED` receipt never contributes to anything downstream. The donor's `lifetime_tax_value_cents` is recomputed as the sum of `deductible_value_cents` over the donor's `ISSUED` receipts only, and the act of issuance increments the donor site's `version` by one — which is exactly what the `expected_donor_version` guard of §2.6 watches. Donors and admins can review the full history, both `ISSUED` and `AMENDED`, through the per-donor receipt listing with its optional `status` filter.

## 4. Endpoint Definitions

Creation of a new resource answers HTTP 201 with the created resource; reads, modifications, lifecycle transitions, and action calls answer HTTP 200 with the affected resource (or the requested payload for reads). All responses use the envelope of §2.2, and all errors use the codes of §5 with the trigger conditions scattered through §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock to `to_iso8601`; lazily expires past-window offers and releases coolers past their cleaning deadlines | DispatchAdmin |
| POST | /api/donor-sites | Onboard a donor site (enters `PENDING_REVIEW`) | DispatchAdmin |
| GET | /api/donor-sites/{id} | Get a donor site including computed aggregates | DispatchAdmin, DonorCoordinator |
| PATCH | /api/donor-sites/{id}/status | Donor lifecycle: approve, suspend, reinstate (resets `strike_count`), deactivate | DispatchAdmin |
| GET | /api/donor-sites/{id}/donation-offers | List a donor's offers, optional `status` filter | DispatchAdmin, DonorCoordinator |
| GET | /api/donor-sites/{id}/tax-receipts | List a donor's tax receipts in all statuses, optional `status` filter | DispatchAdmin, DonorCoordinator |
| POST | /api/donor-sites/{id}/tax-receipts | Issue a tax receipt for a period; supersedes an identical-period `ISSUED` receipt; OCC-guarded | DispatchAdmin |
| POST | /api/recipient-agencies | Register a recipient agency with per-category capacities | DispatchAdmin |
| GET | /api/recipient-agencies/{id} | Get an agency including committed and received aggregates | DispatchAdmin, AgencyCoordinator |
| POST | /api/volunteer-drivers | Register a volunteer driver (enters `ONBOARDING`) | DispatchAdmin |
| GET | /api/volunteer-drivers/{id} | Get a driver including `reliability_score` | DispatchAdmin, VolunteerDriver |
| PATCH | /api/volunteer-drivers/{id}/status | Driver lifecycle: activate, suspend (cascades), reinstate (score resets to 80) | DispatchAdmin |
| POST | /api/volunteer-drivers/{id}/availability-windows | Declare an availability window (driver must be `ACTIVE`; half-open overlap check) | VolunteerDriver |
| GET | /api/volunteer-drivers/{id}/availability-windows | List a driver's availability windows, optional `status` filter | DispatchAdmin, VolunteerDriver |
| POST | /api/coolers | Add a cooler to the cold-chain inventory | DispatchAdmin |
| GET | /api/coolers/{id} | Get a cooler; `CLEANING`/`QUARANTINED` lazily resolve to `AVAILABLE` | DispatchAdmin |
| GET | /api/coolers/{id}/cooler-reservations | List a cooler's reservations, optional `status` filter | DispatchAdmin |
| POST | /api/donation-offers | Create an offer in `DRAFT` (caller must be the donor site's coordinator) | DonorCoordinator |
| GET | /api/donation-offers/{id} | Get an offer; lazily expires `OPEN`/`MATCHED` offers past their window | DispatchAdmin, DonorCoordinator |
| PATCH | /api/donation-offers/{id}/status | Publish (`DRAFT`→`OPEN`) or cancel; donor-initiated cancel of a committed offer auto-files a strike | DonorCoordinator, DispatchAdmin |
| POST | /api/rescue-runs | Dispatch a rescue run against an `OPEN` offer; selectors match omitted driver/agency/coolers; OCC-guarded | DispatchAdmin |
| GET | /api/rescue-runs | List and filter runs by `offer_id`, `agency_id`, `driver_id`, `status` | DispatchAdmin |
| GET | /api/rescue-runs/{id} | Get a run including both `run_status` and `safety_status` | DispatchAdmin, VolunteerDriver, AgencyCoordinator |
| POST | /api/rescue-runs/{id}/respond | Assigned driver accepts (`PROPOSED`→`CONFIRMED`) or declines (full release, offer re-opens) | VolunteerDriver |
| POST | /api/rescue-runs/{id}/record-pickup | Assigned driver records pickup time/temperature and signs the liability attestation | VolunteerDriver |
| POST | /api/rescue-runs/{id}/fail | Fail the run; stage-dependent teardown, fault attribution, strike auto-filing | VolunteerDriver, DispatchAdmin |
| POST | /api/rescue-runs/{id}/record-delivery | Assigned driver records arrival time/temperature and scale weight; computes the danger-zone verdict | VolunteerDriver |
| POST | /api/rescue-runs/{id}/verify-delivery | Agency coordinator countersigns and closes the rescue | AgencyCoordinator |
| GET | /api/rescue-runs/{id}/temperature-logs | List a run's temperature logs | DispatchAdmin, VolunteerDriver, AgencyCoordinator |
| GET | /api/rescue-runs/{id}/cooler-reservations | List a run's cooler reservations, optional `status` filter | DispatchAdmin |
| GET | /api/rescue-runs/{id}/strike-reports | List the strike reports auto-filed for a run, optional `status` filter | DispatchAdmin |
| POST | /api/strike-reports/{id}/adjudicate | Uphold or waive a `FILED` strike; segregation of duties applies | DispatchAdmin |
| POST | /api/rate-cards | Publish a per-category FMV/basis rate card with a non-overlapping effective window | DispatchAdmin |

## 5. Error Code Catalogue

Trigger conditions for each code live in the §2 and §3 narratives; this catalogue is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_DONOR_NOT_FOUND | 404 |
| ERR_AGENCY_NOT_FOUND | 404 |
| ERR_DRIVER_NOT_FOUND | 404 |
| ERR_COOLER_NOT_FOUND | 404 |
| ERR_OFFER_NOT_FOUND | 404 |
| ERR_RUN_NOT_FOUND | 404 |
| ERR_STRIKE_REPORT_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_DONOR_NOT_ACTIVE | 409 |
| ERR_DRIVER_NOT_ACTIVE | 409 |
| ERR_OFFER_NOT_OPEN | 409 |
| ERR_PICKUP_WINDOW_PAST | 409 |
| ERR_RUN_NOT_IN_EXPECTED_STATE | 409 |
| ERR_STRIKE_NOT_FILED | 409 |
| ERR_STALE_OFFER_VERSION | 412 |
| ERR_STALE_DONOR_VERSION | 412 |
| ERR_DRIVER_NOT_COLD_CHAIN_CERTIFIED | 409 |
| ERR_SAFETY_VIOLATION_AT_PICKUP | 409 |
| ERR_SAFETY_VERDICT_VIOLATION | 409 |
| ERR_AVAILABILITY_WINDOW_OVERLAP | 409 |
| ERR_DRIVER_WINDOW_MISSING | 409 |
| ERR_COOLER_UNAVAILABLE | 409 |
| ERR_RATE_CARD_WINDOW_OVERLAP | 409 |
| ERR_AGENCY_CATEGORY_NOT_ACCEPTED | 409 |
| ERR_DRIVER_CAPACITY_EXCEEDED | 409 |
| ERR_AGENCY_CAPACITY_EXCEEDED | 409 |
| ERR_INSUFFICIENT_COOLER_CAPACITY | 409 |
| ERR_DELIVERY_OVERAGE_EXCEEDED | 409 |
| ERR_RECEIPT_NO_VERIFIED_RESCUES | 409 |
| ERR_NO_RATE_CARD_EFFECTIVE | 409 |
| ERR_NO_ELIGIBLE_DRIVER | 409 |
| ERR_NO_ELIGIBLE_AGENCY | 409 |
| ERR_SELF_ADJUDICATION_FORBIDDEN | 403 |
