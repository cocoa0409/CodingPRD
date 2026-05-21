# Freight Brokerage API — Product Requirements Document

## 1. Introduction

Freight brokers sit between shippers who need goods moved and motor carriers who own the trucks. The day-to-day job is a high-frequency, low-margin negotiation: a load arrives priced against either a pre-negotiated lane contract or the live spot market, a carrier with valid federal authority and current insurance has to be matched to it, the carrier reports back actual arrival and departure times that can shift the final price through detention and accessorial charges, an invoice is cut and frequently factored (sold) to a financing house for immediate cash, and shippers occasionally file claims that claw back part of the receivable and bruise the carrier's safety record. None of these dimensions are independent: a successful claim on a factored invoice triggers recourse against the brokerage; a SmartWay-required shipper paired with a non-SmartWay carrier surfaces the breach only at claim time, doubling the safety penalty. This document specifies the API that runs that machinery for a single tenanted brokerage instance.

The system has to keep five clocks aligned at once — the regulatory clock (insurance expiry, FMCSA authority), the commercial clock (rate-contract effective windows, pickup windows, quote expiry), the operational clock (pickup, departure, arrival, delivery), the financial clock (invoice issuance, factoring advance, recourse), and the dispute clock (open, review, counter-offer, resolution). To make those clocks driveable in test, the server exposes its own logical clock that platform administrators advance explicitly; every temporal predicate in the system reads from that clock. Conversely, all monetary values are in integer cents — the only floating-point arithmetic in the system is the marginal factoring-haircut tier rates, and the result of that arithmetic is rounded once, at the end, to the nearest cent.

The reader of this document is the engineer implementing that API. Each section of §2 fixes a cross-cutting contract; §3 walks the business lifecycle and is where most of the rules live. The endpoint table in §4 is intentionally minimal — request/response shapes are described in the §3 narratives that surround each transition.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` (the calling principal's identifier) and `X-User-Role` (one of the five role names enumerated below). A request that omits either header, or carries a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request that carries a well-formed role which is not authorised for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Both rules are checked before any other validation runs.

The five roles are:

- `PlatformAdmin` — operator persona; creates brokerages and drives the test clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example in audit trails) but does not compare it to any entity's `id`.
- `BrokerOps` — brokerage employees managing shippers, contracts, quotes, loads, invoices, and disputes. When `X-User-Role` is `BrokerOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `CarrierOps` — the brokerage's carrier-onboarding team, managing the carrier qualification lifecycle. When `X-User-Role` is `CarrierOps`, `X-User-ID` is likewise opaque.
- `ShipperUser` — an end-user acting as a specific shipper. When `X-User-Role` is `ShipperUser`, `X-User-ID` is the `id` of the acting `Shipper`; ownership checks on any resource that references a `Shipper` (a `QuoteRequest`, a `Load`, an `Invoice`, a `DisputeClaim`) compare the resource's `shipper_id` to `X-User-ID`. A `ShipperUser` accessing another shipper's resource is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.
- `CarrierUser` — an end-user acting as a specific carrier. When `X-User-Role` is `CarrierUser`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on any resource that references a `Carrier` (notably `Load.carrier_id`) compare the foreign key to `X-User-ID`, and a mismatch yields `ERR_INSUFFICIENT_PERMISSIONS`.

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

List endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, has a minimum value of 1 and a maximum value of 100; a request that specifies a value outside that range is rejected with `ERR_INVALID_REQUEST`. `offset` defaults to 0 and must be a non-negative integer. List responses sort by `created_at` ascending. The `meta` envelope on a list response carries `limit`, `offset`, `total_count` (the total number of rows matching the query, ignoring `limit`/`offset`) and `has_more` (true when `offset + limit < total_count`, false otherwise).

### 2.4. Resource Identifiers, Timestamps and Versioning

Every persisted resource exposes a server-minted `id` which is a UUID with no type prefix, returned as a plain string. Most resources additionally carry three lifecycle fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every server-side mutation of the resource (including state transitions, computed-field recomputations, and side-effect cascades that touch the resource). Whenever a resource is mutated, `updated_at` is set to the current clock value and `version` is incremented.

Two entities are deliberately exempt from the full property set because they exist as immutable financial records: `Invoice` and `FactoringAdvance`. Both carry `id` and `created_at` only — they have no `updated_at` and no `version`. An `Invoice`'s parallel-status fields (`factoring_status`, `settlement_status`) and its computed money fields (`amount_paid_cents`, `amount_credited_cents`, `balance_due_cents`, `invoice_total_cents`) are updated in place as cascades fire, but the row itself does not carry a `version` and clients cannot pin optimistic-concurrency expectations on invoice rows.

### 2.5. Server Clock and Test Drivers

Every brokerage carries a server-controlled clock value, `clock_now_iso`. Wherever the specification refers to "the current time" — insurance expiry checks, pickup-window expiry, rate-contract effective-window resolution, quote-expiry sweeps — the value compared is `clock_now_iso` on the owning `Brokerage`, never wall-clock time. The clock advances only via the platform-admin clock-advance capability, which takes a `to_iso` request body field carrying the new ISO 8601 timestamp the clock is to be set to. Advancing the clock also runs a quote-expiry sweep that transitions every `QuoteRequest` in `OPEN` or `QUOTED` whose `pickup_window_end` is now earlier than `clock_now_iso` into the `EXPIRED` terminal state. An equivalent sweep capability is exposed as a standalone administrative operation so that tests can trigger expiry without moving the clock — it processes the same expiry rule on whatever the clock currently reads.

### 2.6. Monetary Units, Precision and Rounding Discipline

All monetary fields end in `_cents` and are stored as non-negative integers representing whole cents. Every calculation in this system produces an integer-cent result; intermediate floating-point arithmetic is permitted only where the formula explicitly calls for it (the factoring haircut tier rates are the only such case), and the result is rounded once, at the end of the calculation, half-up to the nearest whole cent — meaning 0.5 cents and above rounds up to the next cent, anything below 0.5 cents rounds down. Per-tier intermediate rounding is forbidden in the factoring haircut: the implementation must accumulate the unrounded tier contributions, sum them, and round the final scalar.

Detention follows an analogous pinning rule with a different shape: time is bucketed into 15-minute increments **before** monetary multiplication, never after. Concretely, the chargeable time is first rounded up to the next whole 15-minute increment (so that a single chargeable minute counts as one full 15-minute increment, not one-fifteenth of one), and the resulting integer number of increments is then multiplied by the per-increment cent rate. The alternative ordering — converting the rate to a per-minute fraction, multiplying by chargeable minutes, and rounding the resulting cents at the end — is explicitly forbidden because it produces a different answer on partial increments.

The carrier safety score is in integer points, not cents, and is likewise non-negative: every deduction is floored at zero.

### 2.7. Optimistic Concurrency, Serialization and Race Outcomes

Every mutating endpoint that targets a `version`-bearing resource accepts an optional `version` integer in the request body. When supplied, the server compares it to the persisted `version` before applying the mutation; a mismatch is rejected with `ERR_STALE_DATA`. When omitted, the version check is skipped and the mutation proceeds against the latest persisted state. Successful mutations always increment `version` by one.

Beyond per-row optimistic locking, several specific races are resolved with named errors:

- Two simultaneous quote-acceptance attempts on the same `QuoteRequest` serialize to first-writer-wins on `QuoteRequest.status`; the loser sees `ERR_QUOTE_NOT_QUOTED` because the winner has already advanced status out of `QUOTED`.
- Two simultaneous carrier-acceptance attempts on the same `TENDERED` load serialize to first-writer-wins on `Load.status`; the loser sees `ERR_LOAD_NOT_TENDERED`.
- Two simultaneous factoring attempts on the same invoice serialize to first-writer-wins on `Invoice.factoring_status`; only one `FactoringAdvance` is created, and the loser sees `ERR_INVOICE_NOT_FACTORABLE`.
- A factoring attempt racing against a dispute-claim filing on the same invoice resolves as follows: if the dispute lands first, the factoring attempt sees `ERR_INVOICE_HAS_OPEN_DISPUTE`; if the factoring lands first, the dispute filing is rejected with `ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING`. Exactly one of the two operations succeeds.
- Concurrent qualification and revocation attempts on the same carrier serialize to first-writer-wins on `Carrier.status`; the loser of the race sees the state-precondition error that fits its own operation — typically `ERR_CARRIER_NOT_SUSPENDED` when a revocation arrives after the carrier has already been re-qualified.

### 2.8. Tenancy and Nested Resource Resolution

Every URL path is rooted under `/brokerages/{brokerageId}` and is resolved left to right. The `brokerageId` is checked first; an unresolved value yields `ERR_BROKERAGE_NOT_FOUND`. Nested segments — `{shipperId}`, `{carrierId}`, `{quoteId}`, `{contractId}`, `{loadId}`, `{chargeId}`, `{invoiceId}`, `{claimId}` — are then resolved in path order, each producing its own `ERR_<RESOURCE>_NOT_FOUND` (for example `ERR_SHIPPER_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_QUOTE_REQUEST_NOT_FOUND`, `ERR_RATE_CONTRACT_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_ACCESSORIAL_CHARGE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_DISPUTE_CLAIM_NOT_FOUND`). A nested resource that belongs to a different parent than the one named in the path is treated as not found rather than as a permission violation — for example, a `Shipper` whose `brokerage_id` does not match the path's `brokerageId` yields `ERR_SHIPPER_NOT_FOUND`. Body-referenced identifiers (`carrier_id` on tender, `rate_contract_id` on a quote request, `quote_request_id` on tender, `invoice_id` references implicit in dispute creation) are validated after the path resolves and likewise produce the same `NOT_FOUND` error family.

### 2.9. Validation Priority Ordering

When multiple validations apply to a single request, they are evaluated in this strict order and the first failure is returned:

1. Header presence and well-formedness — yielding `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorisation against the RBAC matrix — yielding `ERR_INSUFFICIENT_PERMISSIONS`.
3. Path-segment ID existence, left to right — yielding the appropriate `ERR_<RESOURCE>_NOT_FOUND`.
4. Body-referenced ID existence — yielding the appropriate `ERR_<RESOURCE>_NOT_FOUND`.
5. Target-entity state preconditions — for example `ERR_LOAD_NOT_TENDERED`, `ERR_QUOTE_NOT_QUOTED`, `ERR_INVOICE_NOT_FACTORABLE`, `ERR_CARRIER_NOT_SUSPENDED`.
6. Carrier qualification / insurance / SmartWay gates on tender or carrier-accept — `ERR_CARRIER_NOT_QUALIFIED` taking precedence over the insurance and SmartWay checks where they overlap; the load-tender endpoint and the carrier-accept endpoint are the two scopes for this combined gate.
7. Insurance-expiry check on qualify, requalify, and carrier-accept — `ERR_INSURANCE_EXPIRED`.
8. SmartWay carrier-shipper match on tender and carrier-accept — `ERR_SMARTWAY_REQUIRED`.
9. Rate-contract ambiguity at quote time — `ERR_RATE_CONTRACT_AMBIGUOUS`.
10. Rate-contract overlap on creation — `ERR_RATE_CONTRACT_OVERLAP`.
11. Carrier MC#/USDOT uniqueness on creation — `ERR_CARRIER_AUTHORITY_DUPLICATE`.
12. Dispute-claim amount sanity at filing — `ERR_CLAIM_AMOUNT_INVALID`.
13. Factoring eligibility (zero payments, zero credits, no open disputes) — `ERR_INVOICE_NOT_FACTORABLE`.
14. Dispute-after-factoring guard — `ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING`.
15. Shipper credit-limit check at quote acceptance — `ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED`.
16. Quote-expiry check at quote acceptance — `ERR_QUOTE_EXPIRED`.
17. Delivery-time sanity at delivery — `ERR_INVALID_DELIVERY_TIMES`.
18. Accessorial-pending guard at invoicing — `ERR_ACCESSORIAL_PENDING`.

Implementations must follow this ordering because tests pin specific error IDs on requests that fail multiple checks simultaneously. In particular, the state-precondition check (priority 5) runs before any business safety check (priority 6 onward), so attempting to tender a load on a carrier that is `SUSPENDED` returns `ERR_CARRIER_NOT_QUALIFIED` only if the *load* is already in the right state for tendering; if the underlying quote is in the wrong state, the state-precondition error fires first.

## 3. Business Logic & Workflows

### 3.1. Brokerage Setup and the Server Clock

A `PlatformAdmin` creates a brokerage by supplying its `name`, its `mc_number`, and its `factoring_reserve_pct` — the holdback percentage retained on every factoring advance, expressed as a number from 0 to 100 with two decimal places. Two optional fields tune the brokerage-wide detention pricing: `detention_free_minutes`, defaulting to 120, is the free time before detention begins to accrue on any load this brokerage tenders; `detention_rate_cents_per_15min`, defaulting to 1500, is the cents the brokerage charges per 15-minute increment of chargeable detention. At creation the brokerage's `clock_now_iso` is initialised to the current real-world time, after which it advances only by explicit administrative action.

Clock advancement is an admin-only test-driving capability that takes a `to_iso` ISO 8601 timestamp. The supplied instant becomes the new `clock_now_iso`; in the same transaction every `OPEN` or `QUOTED` `QuoteRequest` whose `pickup_window_end` is earlier than the new clock value is moved into `EXPIRED`. The parallel administrative sweep capability re-runs that same expiry pass against whatever the clock currently reads, which is useful for tests that have set up data without moving the clock. The clock value never moves backward, and the value on each brokerage is independent.

### 3.2. Shipper Onboarding and Credit Posture

A `BrokerOps` operator creates a shipper by supplying `company_name`, the boolean `smartway_required` indicating whether only SmartWay-certified carriers may haul this shipper's loads, and a `credit_limit_cents` integer cap on outstanding invoiced amount. On creation `status` is set to `ACTIVE` and `outstanding_invoiced_cents` to 0. A shipper can be moved to `SUSPENDED` by a `BrokerOps` operator; while `SUSPENDED`, attempts to file a new `QuoteRequest` against that shipper are rejected with `ERR_SHIPPER_SUSPENDED`, as are broker quotes against an already-open quote request belonging to a now-suspended shipper.

`outstanding_invoiced_cents` is a derived field equal to the sum of `balance_due_cents` across this shipper's non-`VOIDED` invoices. The system maintains it incrementally rather than recomputing on every read: at invoice issuance the shipper's `outstanding_invoiced_cents` is increased by the invoice total, and at the point the invoice transitions to `PAID` or `WRITTEN_OFF`, the shipper's `outstanding_invoiced_cents` is decreased by the original frozen `invoice_total_cents` of that invoice — not by the current `balance_due_cents`, which by definition is zero by the time of that transition.

### 3.3. Carrier Qualification, Suspension, Requalification, Revocation

A carrier is onboarded by a `CarrierOps` operator who supplies the carrier's `legal_name`, its `mc_number`, its `usdot_number`, its `insurance_expires_on` timestamp, and optionally `smartway_certified` (defaulting to false). The new carrier lands in `PENDING_QUALIFICATION` with `safety_score` initialised to 1000. The MC# and USDOT number must each be unique per brokerage across all non-`REVOKED` carriers: a duplicate filing yields `ERR_CARRIER_AUTHORITY_DUPLICATE`. Revoked carriers are explicitly excluded from the uniqueness set, so an `mc_number` belonging to a `REVOKED` row may be re-registered.

Qualifying a `PENDING_QUALIFICATION` carrier advances it to `QUALIFIED`. The qualification check requires both `mc_number` and `usdot_number` to be non-empty (failure yields `ERR_INVALID_CARRIER_AUTHORITY`) and the `insurance_expires_on` timestamp to be strictly after the brokerage clock (failure yields `ERR_INSURANCE_EXPIRED`). If `safety_score` was previously null it is initialised to 1000 as a side effect. Attempting to qualify a carrier not currently in `PENDING_QUALIFICATION` yields `ERR_CARRIER_NOT_PENDING`.

Suspension can be triggered two ways. A `CarrierOps` operator can manually suspend a `QUALIFIED` carrier; this fails with `ERR_CARRIER_HAS_OPEN_LOADS` if the carrier has any load currently in `TENDERED`, `ACCEPTED`, or `IN_TRANSIT`. The system also suspends carriers automatically whenever `safety_score` drops below the suspend threshold of 600 points; that cascade fires from the safety-score update calculation described in 3.9 and carries no precondition check because the system triggers it. Either way, while a carrier is `SUSPENDED`, no new tenders may be placed on them.

A `SUSPENDED` carrier can be moved back to `QUALIFIED` by a `CarrierOps` operator via the requalification capability. Two preconditions apply: `insurance_expires_on` must still be strictly after the brokerage clock (otherwise `ERR_INSURANCE_EXPIRED`), and `safety_score` must be at least 700 points (otherwise `ERR_SAFETY_SCORE_TOO_LOW`). Attempting to requalify a carrier not in `SUSPENDED` yields `ERR_CARRIER_NOT_SUSPENDED`. A carrier may legitimately oscillate `SUSPENDED → QUALIFIED → SUSPENDED → …` over its lifetime.

Revocation is a one-way terminal move available only from `SUSPENDED`: a `CarrierOps` operator drives the carrier into `REVOKED`. Attempting to revoke a non-`SUSPENDED` carrier yields `ERR_CARRIER_NOT_SUSPENDED`. The side effect is that the carrier's MC# and USDOT number are released from the uniqueness set described above, so the same `mc_number` may be re-onboarded under a new row.

### 3.4. Rate Contracts and the Spot/Contract Pricing Engine

A `BrokerOps` operator establishes a rate contract by supplying the counterparty `shipper_id`, the lane `lane_origin_zip` and `lane_destination_zip`, the `equipment_type` (one of `DRY_VAN`, `REEFER`, `FLATBED`), the `flat_rate_cents` per-load all-in linehaul price, an `effective_from` start timestamp (inclusive), and an `effective_to` end timestamp (exclusive). The validity window must be non-empty — `effective_to` must be strictly after `effective_from`. A rate contract lands in `ACTIVE` status on creation. Termination via the `BrokerOps`-only termination capability moves it to `TERMINATED`.

Before creation, the server checks that no other `ACTIVE` rate contract on the same shipper, lane (origin ZIP + destination ZIP), and equipment type already covers any instant in the new contract's `[effective_from, effective_to)` window. An overlap is rejected with `ERR_RATE_CONTRACT_OVERLAP`. This invariant is what guarantees that, at any given clock instant, at most one `ACTIVE` contract resolves for a given shipper-lane-equipment combination.

When a broker quotes a quote request, the pricing engine runs. If the quote request supplied a `rate_contract_id`, the server tries to resolve it: the contract must exist, be `ACTIVE`, belong to the same `shipper_id` as the quote, have `lane_origin_zip` equal to the quote's `origin_zip`, have `lane_destination_zip` equal to the quote's `destination_zip`, have its `equipment_type` equal to the quote's `equipment_type`, and have its effective window contain the brokerage clock (`effective_from` no later than, and `effective_to` strictly after, the current clock value). If exactly one rate contract matches, the quote's `rate_source` is set to `CONTRACT` and `quoted_linehaul_cents` is set to the contract's `flat_rate_cents`. If no rate contract matches, or if `rate_contract_id` was not supplied at all, the engine falls through to the spot path with `rate_source` set to `SPOT`. If more than one `ACTIVE` rate contract somehow matches — the overlap invariant should normally prevent this, but the check is defensive — the request is rejected with `ERR_RATE_CONTRACT_AMBIGUOUS`.

On the spot path, the quoted linehaul is computed from a base price and a distance-proportional component, both keyed to the equipment type. The base price is 30,000 cents for `DRY_VAN`, 50,000 cents for `REEFER`, and 40,000 cents for `FLATBED`. The distance is treated as the absolute difference between the destination ZIP and the origin ZIP interpreted as integers — a deliberately simple proxy for actual mileage — and the per-unit rate is 10 cents for `DRY_VAN`, 18 cents for `REEFER`, and 14 cents for `FLATBED`. The quoted linehaul in cents is therefore the equipment-specific base plus the integer ZIP-difference multiplied by the equipment-specific per-unit rate. All operands are integers and the result is an integer; no rounding is required.

### 3.5. Quote Request Workflow

A `ShipperUser` files a quote request against their own shipper by supplying `origin_zip`, `destination_zip`, `equipment_type`, a `pickup_window_start` and a `pickup_window_end` timestamp, and optionally a `rate_contract_id`. The window must be non-empty: `pickup_window_end` must be strictly after `pickup_window_start`. The quote lands in `OPEN` status. A request filed against a shipper whose `status` is `SUSPENDED` is rejected with `ERR_SHIPPER_SUSPENDED`.

A `BrokerOps` operator then quotes the request, advancing it from `OPEN` to `QUOTED`. As a side effect, the pricing engine described in 3.4 sets `rate_source` and `quoted_linehaul_cents`. Attempting to quote a request not in `OPEN` yields `ERR_QUOTE_NOT_OPEN`; quoting a request whose shipper is now `SUSPENDED` likewise yields `ERR_SHIPPER_SUSPENDED`.

A `ShipperUser` then either accepts or rejects the quote. Acceptance advances `QUOTED → ACCEPTED` and carries two preconditions. The brokerage clock must be no later than `pickup_window_end` — a stale quote is rejected with `ERR_QUOTE_EXPIRED`. Additionally, the shipper's current `outstanding_invoiced_cents` plus the quote's `quoted_linehaul_cents` must not exceed the shipper's `credit_limit_cents`; a breach yields `ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Rejection advances `QUOTED → REJECTED` unconditionally. Attempting either operation on a quote not currently in `QUOTED` yields `ERR_QUOTE_NOT_QUOTED`.

Quote requests in `OPEN` or `QUOTED` whose `pickup_window_end` has passed are swept into `EXPIRED` automatically whenever the brokerage clock advances, as described in 3.1. `ACCEPTED`, `REJECTED`, and `EXPIRED` are terminal: a quote in any of those three states cannot be quoted, accepted, or rejected again.

### 3.6. Load Tender, Acceptance, Transit and Delivery

A `BrokerOps` operator tenders a load by supplying `quote_request_id` (which must refer to a `QuoteRequest` in `ACCEPTED` — otherwise `ERR_QUOTE_NOT_ACCEPTED`) and `carrier_id`. The new load is identified by its server-minted `id`; downstream resources that hang off the load (accessorial charges via `load_id`, the invoice via `load_id`) carry that identifier as their parent reference. As side effects, the load's `rate_source` and `linehaul_cents` are copied from the source quote, and the carrier-gate checks described below run. The load lands in `TENDERED`. The carrier-gate checks require the carrier to be in `QUALIFIED` (otherwise `ERR_CARRIER_NOT_QUALIFIED`), the carrier's `insurance_expires_on` to be strictly after the clock (otherwise `ERR_INSURANCE_EXPIRED`), and — if the owning shipper has `smartway_required` set to true — the carrier's `smartway_certified` to be true (otherwise `ERR_SMARTWAY_REQUIRED`). These same three gates are re-applied when the carrier accepts the tender, because the carrier's qualification, insurance, or SmartWay status may have changed in the interim.

A `CarrierUser` accepts the tender, advancing `TENDERED → ACCEPTED`. This operation is restricted to the carrier whose `id` matches `X-User-ID`; any other carrier sees `ERR_INSUFFICIENT_PERMISSIONS`. Two simultaneous acceptance attempts on the same `TENDERED` load serialize as described in 2.7. Accepting a load not in `TENDERED` yields `ERR_LOAD_NOT_TENDERED`.

The carrier then departs the pickup, moving the load from `ACCEPTED` to `IN_TRANSIT`. Attempting to depart a load not in `ACCEPTED` yields `ERR_LOAD_NOT_ACCEPTED`.

Delivery moves the load from `IN_TRANSIT` to `DELIVERED`. The carrier supplies `actual_arrive_at` (arrival at the consignee) and `actual_depart_at` (departure from the consignee). The latter must be no earlier than the former; otherwise the request is rejected with `ERR_INVALID_DELIVERY_TIMES`. Attempting to deliver a load not in `IN_TRANSIT` yields `ERR_LOAD_NOT_IN_TRANSIT`. As a side effect, the load's `provisional_detention_cents` is computed by the provisional-detention calculation described in 3.7.

Cancellation moves a load from either `TENDERED` or `ACCEPTED` into the terminal `CANCELLED` state and is allowed for both `BrokerOps` and `ShipperUser` (the latter only on its own shipper's loads). Cancellation from any later state is rejected with `ERR_LOAD_NOT_CANCELLABLE`. A cancelled load produces no invoice, and the source `QuoteRequest` remains in its terminal `ACCEPTED` state — cancellation does not undo the quote acceptance.

### 3.7. Accessorial Charges and Detention at Delivery and at Invoice

While a load is between `ACCEPTED` and `DELIVERED`, a `CarrierUser` may file accessorial charges against it. Each charge carries a `charge_type` (one of `LAYOVER`, `TONU`, `REWEIGH`, `LUMPER` — detention is **not** an accessorial because it is computed automatically on the load) and an `amount_cents` integer that must be strictly greater than zero. A charge lands in `REQUESTED`. A `BrokerOps` operator then either approves or denies it, moving it to `APPROVED` or `DENIED` respectively; approval or denial of a charge already past `REQUESTED` yields `ERR_ACCESSORIAL_NOT_REQUESTED`.

Detention is computed in two passes against the same arrival and departure times. At the moment of delivery, the provisional pass runs: the elapsed minutes between `actual_arrive_at` and `actual_depart_at` are computed as the floor of the second-difference divided by 60. Subtract the brokerage's `detention_free_minutes`; if the result is non-positive, no detention accrues and `provisional_detention_cents` is zero. Otherwise, take the resulting chargeable-minute count, round it up to the next whole 15-minute increment, and multiply the resulting integer number of increments by `detention_rate_cents_per_15min`. The result is the load's `provisional_detention_cents`. This rounding order — ceil-to-15-minute-increment first, then multiply by the per-increment rate — is the mandated calculation order: under no circumstances may the implementation derive a per-minute fractional rate, multiply by chargeable minutes, and round the resulting cents at the end, because for example a single chargeable minute under a 1500-cent per-15-minute rate must produce 1500 cents (one full increment) and not 100 cents (one-fifteenth of an increment).

When a `BrokerOps` operator invoices the load (advancing it from `DELIVERED` to `INVOICED`), the same provisional formula is rerun, but using whatever the brokerage's `detention_free_minutes` and `detention_rate_cents_per_15min` are at the moment of invoicing. These values may have been edited between delivery and invoicing, in which case the recomputed result will differ; the load's `final_detention_cents` is set to the new computation and is the authoritative figure. The invoicing operation has one further precondition: every `AccessorialCharge` row on the load must be either `APPROVED` or `DENIED` — none may remain in `REQUESTED`. A pending charge yields `ERR_ACCESSORIAL_PENDING`. The `accessorial_total_cents` accumulated on the load is the sum of `amount_cents` over all `APPROVED` charges (denied charges contribute nothing). The new `Invoice` row is created with `linehaul_cents` frozen from the load's `linehaul_cents`, `detention_cents` frozen from `final_detention_cents`, and `accessorial_cents` frozen from `accessorial_total_cents`. The invoice's `invoice_total_cents` is the sum of those three frozen components, `amount_paid_cents` and `amount_credited_cents` initialise to zero, and `balance_due_cents` initialises to `invoice_total_cents`. The invoice's `factoring_status` starts at `NOT_FACTORED` and its `settlement_status` starts at `ISSUED`. At the same time, the owning shipper's `outstanding_invoiced_cents` is increased by the new invoice's full `invoice_total_cents`.

### 3.8. Factoring Advances and the Haircut Tier Math

Factoring lets the brokerage sell a fresh invoice to a financing house for immediate cash. A `BrokerOps` operator factors an invoice through the factoring capability; this moves the invoice's `factoring_status` from `NOT_FACTORED` to `FACTORED`. Three preconditions must hold simultaneously: the `settlement_status` must be `ISSUED`, the `balance_due_cents` must equal the `invoice_total_cents` (no prior cash applied and no prior credits applied), and there must be no `DisputeClaim` on this invoice currently in `OPEN`, `IN_REVIEW`, or `COUNTER_OFFERED`. Any of the first two failing yields `ERR_INVOICE_NOT_FACTORABLE`; an open dispute yields `ERR_INVOICE_HAS_OPEN_DISPUTE`. A second factoring attempt on an already-`FACTORED` or `RECOURSED` invoice likewise yields `ERR_INVOICE_NOT_FACTORABLE`.

The successful factoring operation creates a `FactoringAdvance` row whose `invoice_total_at_advance_cents` is a frozen copy of the invoice's `invoice_total_cents` at the moment of factoring. From that anchor three monetary fields are computed.

The `haircut_cents` — the factor's fee, held off the advance — is computed by a marginal tier schedule. Let T denote `invoice_total_at_advance_cents`. The first 100,000 cents of T (the slice from 0 up to and including 100,000) is charged at 3.0% (rate 0.030). The next 400,000 cents of T (the slice strictly above 100,000 up to and including 500,000) is charged at 2.0% (rate 0.020). Any slice strictly above 500,000 cents is charged at 1.0% (rate 0.010). The implementation allocates T across the three buckets in this order, multiplies each bucket size by its tier rate to produce an unrounded contribution, sums the three contributions, and then rounds that single sum half-up to a whole number of cents. Per-tier intermediate rounding is forbidden because it produces a different result on totals whose tier-boundary residues are near a half-cent.

The `reserve_cents` is the brokerage-wide holdback. It equals `invoice_total_at_advance_cents` multiplied by `factoring_reserve_pct`, divided by 100, with the result rounded half-up to a whole number of cents.

The `advanced_cents` — the cash wired to the brokerage — equals `invoice_total_at_advance_cents` minus `haircut_cents` minus `reserve_cents`.

At factoring time, the brokerage treats the invoice's face value as paid against the receivable: `Invoice.amount_paid_cents` is increased by `invoice_total_at_advance_cents`, which drives `balance_due_cents` to zero. The factor now holds the underlying receivable. The invoice does **not** transition to `PAID` in this state, because the parallel settlement dimension only auto-advances to `PAID` when `balance_due_cents` reaches zero **and** `factoring_status` is something other than `FACTORED`; while the invoice is `FACTORED` it remains `ISSUED` on the settlement axis.

`recourse_owed_cents` is initially zero on a freshly factored advance; it becomes non-zero only on the `FACTORED → RECOURSED` cascade described in 3.9.

### 3.9. Dispute Claims, Credit Cascades and Carrier Safety

A `ShipperUser` files a dispute claim against an `Invoice` belonging to their own shipper by supplying `claim_type` (one of `DAMAGE`, `SHORTAGE`, `OVERCHARGE`, `LATE_DELIVERY`) and `claimed_cents`. The claimed amount must be strictly greater than zero and must not exceed the invoice's current `balance_due_cents` at the moment of filing; either violation is rejected with `ERR_CLAIM_AMOUNT_INVALID`. Filing a dispute on an invoice whose `factoring_status` is `FACTORED` or `RECOURSED` is rejected with `ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING` — the dispute window closes once a financing house owns the receivable. The new claim lands in `OPEN`.

A `BrokerOps` operator opens the claim for review (advancing `OPEN → IN_REVIEW`). From `IN_REVIEW`, the broker has three onward options: counter, resolve, or escalate. Attempting any of these on a claim not in `IN_REVIEW` yields `ERR_CLAIM_NOT_IN_REVIEW`. From `OPEN` or `IN_REVIEW`, the shipper may withdraw the claim into the terminal `WITHDRAWN` state; withdrawal from any other state yields `ERR_CLAIM_NOT_OPEN`. Start-review on a claim not in `OPEN` yields `ERR_CLAIM_NOT_OPEN` as well.

The counter capability accepts a `counter_offer_cents` integer. It must be strictly greater than zero and strictly less than the original `claimed_cents`; either violation is rejected with `ERR_COUNTER_OFFER_INVALID`. The claim moves `IN_REVIEW → COUNTER_OFFERED`. From `COUNTER_OFFERED` the shipper can either accept the counter (advancing to `RESOLVED` with `settled_credit_cents` set to the counter amount) or reject it (cycling back to `IN_REVIEW`, with `counter_offer_cents` cleared back to null so the next counter is a fresh offer). Either operation on a claim not in `COUNTER_OFFERED` yields `ERR_CLAIM_NOT_COUNTER_OFFERED`. A claim may oscillate between `IN_REVIEW` and `COUNTER_OFFERED` any number of times before terminating.

The resolve capability is reserved to `BrokerOps` and accepts a `settled_credit_cents` integer. The value must be at least zero, must not exceed the original `claimed_cents`, and must not exceed the invoice's current `balance_due_cents`; any violation is rejected with `ERR_SETTLED_CREDIT_INVALID`. The claim moves `IN_REVIEW → RESOLVED`.

Whenever a claim resolves — whether through broker resolution or shipper acceptance of a counter — a cascade of side effects fires. Let `c` denote the credit amount applied (the `settled_credit_cents` request-body value on broker resolution, or the previously stored `counter_offer_cents` on shipper accept-counter). The invoice's `amount_credited_cents` is increased by `c`. The invoice's `invoice_total_cents` is decreased by `c` — the face value of the receivable shrinks because the shipper no longer owes that portion. The invoice's `balance_due_cents` is then recomputed as `invoice_total_cents` minus `amount_paid_cents` minus `amount_credited_cents`, with a floor of zero. The conservation invariant the system maintains is that the pre-resolution `invoice_total_cents` equals the post-resolution `invoice_total_cents` plus the delta added to `amount_credited_cents`.

Two further cascades may fire from a non-zero `settled_credit_cents`:

- If the invoice's `factoring_status` is `FACTORED` and `c > 0`, the invoice transitions `FACTORED → RECOURSED`. The corresponding `FactoringAdvance.recourse_owed_cents` is set to the credit amount (the factor recoups the face-value difference, so the brokerage owes the factor that much back), and the invoice's `amount_paid_cents` is decreased by the same amount — the brokerage is buying back the receivable to that extent — which has the consequence of restoring the invoice's `balance_due_cents` to the previously-credited portion.
- The carrier on the load underneath the invoice receives a safety-score deduction. The base penalty is keyed to `claim_type`: 100 points for `DAMAGE`, 60 points for `SHORTAGE`, 30 points for `OVERCHARGE`, 40 points for `LATE_DELIVERY`. If the shipper's `smartway_required` is true and the carrier's `smartway_certified` is false — meaning the carrier should not have been tendered in the first place; the breach surfaces only at claim time — an additional 50-point SmartWay-breach penalty is added on top of the base penalty. The carrier's `safety_score` is reduced by the resulting total, with a floor of zero. After the deduction, if `safety_score` is strictly less than 600 the carrier is automatically transitioned `QUALIFIED → SUSPENDED` as a further cascade; this auto-suspension carries no precondition check.

Additionally, if after the cascade the invoice's `balance_due_cents` is exactly zero **and** its `factoring_status` is something other than `FACTORED`, the invoice's `settlement_status` automatically advances to `PAID`. On a `RECOURSED` invoice this auto-settlement does fire because `RECOURSED` is not `FACTORED`.

Escalation moves the claim from `IN_REVIEW` to the terminal `ESCALATED` state — the claim is parked for external arbitration and no credit is applied, no invoice is touched, no safety penalty fires.

### 3.10. Settlement, Write-Off and Recourse

Settlement runs along a dimension parallel to factoring. The invoice's `settlement_status` is independently `ISSUED`, `PAID`, or `WRITTEN_OFF`; its `factoring_status` is independently `NOT_FACTORED`, `FACTORED`, or `RECOURSED`. The two dimensions interact only through the auto-settlement rule: `settlement_status` automatically advances `ISSUED → PAID` whenever `balance_due_cents` reaches zero and `factoring_status` is not `FACTORED`. The side effect of that auto-advance is that the shipper's `outstanding_invoiced_cents` is decreased by the invoice's original frozen `invoice_total_cents` (the pre-credit total, snapshotted at issuance), not by the current shrunken value.

A `BrokerOps` operator can also drive an invoice into `WRITTEN_OFF` via the write-off capability. The operation requires `balance_due_cents` to be strictly positive (a fully-paid invoice yields `ERR_INVOICE_NOTHING_TO_WRITE_OFF`) and requires no `DisputeClaim` on the invoice to currently be `OPEN`, `IN_REVIEW`, or `COUNTER_OFFERED` (otherwise `ERR_INVOICE_HAS_OPEN_DISPUTE`). The write-off increases `amount_credited_cents` by the current `balance_due_cents`, driving the balance to zero, and decreases the shipper's `outstanding_invoiced_cents` by the original frozen `invoice_total_cents`.

The `FACTORED → RECOURSED` transition is purely automatic: it fires whenever a dispute claim resolves on a `FACTORED` invoice with a non-zero settled credit, as described in 3.9. The `recourse_owed_cents` on the `FactoringAdvance` records what the brokerage owes back to the factor. `RECOURSED` is terminal on the factoring axis — a recoursed invoice cannot be re-factored.

The load lifecycle mirrors the invoice settlement. The load enters `INVOICED` when the invoice is issued. As an automatic system cascade, whenever the underlying invoice reaches `balance_due_cents` of zero **and** the invoice's `factoring_status` is not `FACTORED`, the load transitions from `INVOICED` to the terminal `SETTLED` state in the same operation that advances the invoice's `settlement_status` to `PAID`. `SETTLED` and `CANCELLED` are the two terminal states on the load axis.

## 4. Endpoint Definitions

The API is mounted under `/brokerages`. All endpoint paths in this table are absolute. New resources are returned with HTTP 201; non-creating mutations and read endpoints return HTTP 200. Validation failures, state preconditions, race losers, and concurrency mismatches return 4xx status codes per §5. The request and response shapes are not enumerated here — the §3 narratives above describe what each endpoint reads from the request body and writes to the resource.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/brokerages` | Create a brokerage | `PlatformAdmin` |
| GET | `/brokerages/{brokerageId}` | Get a brokerage | `PlatformAdmin`, `BrokerOps`, `CarrierOps`, `ShipperUser`, `CarrierUser` |
| POST | `/brokerages/{brokerageId}/_clock/advance` | Advance the server clock (test driver) | `PlatformAdmin` |
| POST | `/brokerages/{brokerageId}/_sweep/expire-quotes` | Manual quote-expiry sweep (test driver) | `PlatformAdmin` |
| POST | `/brokerages/{brokerageId}/shippers` | Create a shipper | `BrokerOps` |
| GET | `/brokerages/{brokerageId}/shippers` | List shippers | `BrokerOps`, `PlatformAdmin` |
| GET | `/brokerages/{brokerageId}/shippers/{shipperId}` | Get a shipper | `BrokerOps`, `ShipperUser`, `PlatformAdmin` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/suspend` | Suspend a shipper | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/carriers` | Create a carrier | `CarrierOps` |
| GET | `/brokerages/{brokerageId}/carriers` | List carriers | `BrokerOps`, `CarrierOps`, `PlatformAdmin` |
| GET | `/brokerages/{brokerageId}/carriers/{carrierId}` | Get a carrier | `BrokerOps`, `CarrierOps`, `CarrierUser`, `PlatformAdmin` |
| POST | `/brokerages/{brokerageId}/carriers/{carrierId}/qualify` | Qualify a pending carrier | `CarrierOps` |
| POST | `/brokerages/{brokerageId}/carriers/{carrierId}/suspend` | Manually suspend a qualified carrier | `CarrierOps` |
| POST | `/brokerages/{brokerageId}/carriers/{carrierId}/requalify` | Requalify a suspended carrier | `CarrierOps` |
| POST | `/brokerages/{brokerageId}/carriers/{carrierId}/revoke` | Revoke a suspended carrier | `CarrierOps` |
| POST | `/brokerages/{brokerageId}/rate-contracts` | Create an active rate contract | `BrokerOps` |
| GET | `/brokerages/{brokerageId}/rate-contracts` | List rate contracts | `BrokerOps`, `ShipperUser`, `PlatformAdmin` |
| POST | `/brokerages/{brokerageId}/rate-contracts/{contractId}/terminate` | Terminate an active rate contract | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/quote-requests` | File a quote request | `ShipperUser` |
| GET | `/brokerages/{brokerageId}/shippers/{shipperId}/quote-requests/{quoteId}` | Get a quote request | `BrokerOps`, `ShipperUser` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/quote-requests/{quoteId}/quote` | Broker quotes a price | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/quote-requests/{quoteId}/accept` | Shipper accepts the quote | `ShipperUser` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/quote-requests/{quoteId}/reject` | Shipper rejects the quote | `ShipperUser` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/loads` | Tender a load on an accepted quote | `BrokerOps` |
| GET | `/brokerages/{brokerageId}/shippers/{shipperId}/loads/{loadId}` | Get a load | `BrokerOps`, `ShipperUser`, `CarrierUser` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/loads/{loadId}/carrier-accept` | Carrier accepts the tender | `CarrierUser` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/loads/{loadId}/depart` | Carrier departs pickup | `CarrierUser` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/loads/{loadId}/deliver` | Carrier delivers; provisional detention computed | `CarrierUser` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/loads/{loadId}/invoice` | Broker invoices the shipper | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/loads/{loadId}/cancel` | Cancel a tendered or accepted load | `BrokerOps`, `ShipperUser` |
| POST | `/brokerages/{brokerageId}/shippers/{shipperId}/loads/{loadId}/accessorial-charges` | Carrier requests an accessorial | `CarrierUser` |
| POST | `/brokerages/{brokerageId}/accessorial-charges/{chargeId}/approve` | Broker approves an accessorial | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/accessorial-charges/{chargeId}/deny` | Broker denies an accessorial | `BrokerOps` |
| GET | `/brokerages/{brokerageId}/invoices` | List invoices | `BrokerOps`, `ShipperUser`, `PlatformAdmin` |
| GET | `/brokerages/{brokerageId}/invoices/{invoiceId}` | Get an invoice | `BrokerOps`, `ShipperUser`, `PlatformAdmin` |
| POST | `/brokerages/{brokerageId}/invoices/{invoiceId}/factor` | Factor the invoice | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/invoices/{invoiceId}/write-off` | Write off an unpaid invoice | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/invoices/{invoiceId}/dispute-claims` | Shipper files a dispute claim | `ShipperUser` |
| GET | `/brokerages/{brokerageId}/dispute-claims/{claimId}` | Get a dispute claim | `BrokerOps`, `ShipperUser` |
| POST | `/brokerages/{brokerageId}/dispute-claims/{claimId}/start-review` | Broker starts reviewing | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/dispute-claims/{claimId}/counter` | Broker issues a counter-offer | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/dispute-claims/{claimId}/accept-counter` | Shipper accepts the counter | `ShipperUser` |
| POST | `/brokerages/{brokerageId}/dispute-claims/{claimId}/reject-counter` | Shipper rejects the counter | `ShipperUser` |
| POST | `/brokerages/{brokerageId}/dispute-claims/{claimId}/resolve` | Broker resolves with a final credit | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/dispute-claims/{claimId}/escalate` | Broker escalates to arbitration | `BrokerOps` |
| POST | `/brokerages/{brokerageId}/dispute-claims/{claimId}/withdraw` | Shipper withdraws a claim | `ShipperUser` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_BROKERAGE_NOT_FOUND` | 404 |
| `ERR_SHIPPER_NOT_FOUND` | 404 |
| `ERR_CARRIER_NOT_FOUND` | 404 |
| `ERR_QUOTE_REQUEST_NOT_FOUND` | 404 |
| `ERR_RATE_CONTRACT_NOT_FOUND` | 404 |
| `ERR_LOAD_NOT_FOUND` | 404 |
| `ERR_ACCESSORIAL_CHARGE_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_DISPUTE_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_CARRIER_AUTHORITY` | 400 |
| `ERR_INVALID_DELIVERY_TIMES` | 422 |
| `ERR_COUNTER_OFFER_INVALID` | 422 |
| `ERR_SETTLED_CREDIT_INVALID` | 422 |
| `ERR_CLAIM_AMOUNT_INVALID` | 422 |
| `ERR_INSURANCE_EXPIRED` | 409 |
| `ERR_SMARTWAY_REQUIRED` | 409 |
| `ERR_SAFETY_SCORE_TOO_LOW` | 409 |
| `ERR_CARRIER_AUTHORITY_DUPLICATE` | 409 |
| `ERR_CARRIER_HAS_OPEN_LOADS` | 409 |
| `ERR_SHIPPER_SUSPENDED` | 409 |
| `ERR_QUOTE_NOT_OPEN` | 409 |
| `ERR_QUOTE_NOT_QUOTED` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_QUOTE_NOT_ACCEPTED` | 409 |
| `ERR_LOAD_NOT_TENDERED` | 409 |
| `ERR_LOAD_NOT_ACCEPTED` | 409 |
| `ERR_LOAD_NOT_IN_TRANSIT` | 409 |
| `ERR_LOAD_NOT_DELIVERED` | 409 |
| `ERR_LOAD_NOT_CANCELLABLE` | 409 |
| `ERR_CARRIER_NOT_PENDING` | 409 |
| `ERR_CARRIER_NOT_QUALIFIED` | 409 |
| `ERR_CARRIER_NOT_SUSPENDED` | 409 |
| `ERR_ACCESSORIAL_NOT_REQUESTED` | 409 |
| `ERR_ACCESSORIAL_PENDING` | 409 |
| `ERR_INVOICE_NOT_FACTORABLE` | 409 |
| `ERR_INVOICE_HAS_OPEN_DISPUTE` | 409 |
| `ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING` | 409 |
| `ERR_INVOICE_NOTHING_TO_WRITE_OFF` | 409 |
| `ERR_CLAIM_NOT_OPEN` | 409 |
| `ERR_CLAIM_NOT_IN_REVIEW` | 409 |
| `ERR_CLAIM_NOT_COUNTER_OFFERED` | 409 |
| `ERR_RATE_CONTRACT_OVERLAP` | 409 |
| `ERR_RATE_CONTRACT_AMBIGUOUS` | 409 |
| `ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_DATA` | 409 |
