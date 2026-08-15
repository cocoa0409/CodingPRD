# Air Freight Forwarding Consolidation API — Product Requirements Document

## 1. Introduction

Air freight forwarders earn their margin in the space between what shippers tender and what airlines sell. A forwarder procures pallet and container capacity on scheduled flights before it has freight to fill it, then wins or loses money depending on how completely it can consolidate individual customer consignments into that capacity, how accurately it rates each consignment against customer tariffs, and how cleanly it clears the compliance gates — security screening, dangerous goods controls, customs filing — that stand between a dock receipt and a delivered shipment. Every kilogram flown below the purchased allotment is waste; every kilogram over is a rejected tender.

This document specifies an API for running that business end to end. The system covers airline capacity procurement, consolidation of house waybills under master waybills, chargeable-weight rating with quoted-versus-measured volume variants, spot surcharges driven by booking utilization, known-shipper and dangerous-goods screening with strict segregation of duties, customs entry handoff to a licensed broker, transit milestone tracking with exception recording, and cargo claims bounded by Montreal Convention liability limits. Throughout, a logical clock drives time-dependent transitions, so booking cutoffs, rate agreement validity windows, and claim filing deadlines are all evaluated against a controllable server-side clock rather than wall time.

Two commitments shape everything that follows. First, capacity is a scarce, competed resource: consolidation decisions are serialized through optimistic concurrency on the master waybill, and utilization thresholds feed directly back into pricing through the spot surcharge. Second, compliance is not advisory: a dangerous-goods waybill from an unverified shipper cannot even enter screening, a screening officer may never clear their own submission, and the third screening rejection automatically strips a shipper's known-shipper standing.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts and cross-cutting rules that hold for every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted for the attempted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly six roles: `ForwarderOps`, `CapacityPlanner`, `ComplianceOfficer`, `CustomsBroker`, `PricingManager`, and `ClaimsAdjuster`.

For all six roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: when `X-User-Role` is `ForwarderOps`, `CapacityPlanner`, `ComplianceOfficer`, `CustomsBroker`, `PricingManager`, or `ClaimsAdjuster`, the server never compares the header value against any resource's `id` for ownership. The header value is nonetheless recorded in two places where the business workflow demands actor attribution: submitting a house waybill to screening stamps the waybill's `submitted_by_user_id` with the caller's `X-User-ID`, and resolving a screening record stamps the record's `resolved_by_user_id`. Those two stamps are what the segregation-of-duties rule compares (§3.3); no other ownership comparison exists anywhere in the system.

One role mapping is conditional rather than static. On the customs entry transition operation, the permitted role depends on the requested `target_status`: advancing an entry to `HANDED_OFF`, or returning a rejected entry to `PREPARING` for rework, is a `ForwarderOps` action, while advancing an entry to `FILED`, `RELEASED`, or `REJECTED` is a `CustomsBroker` action. A caller holding the wrong role for the requested target receives `ERR_FORBIDDEN_ROLE`.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless an endpoint states otherwise, list responses are sorted by `created_at` in ascending order.

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. Two list endpoints refine the default ordering in §3: screening records of a waybill break `created_at` ties by creation sequence so that within one submit the `SECURITY` record precedes the `DANGEROUS_GOODS` record, and milestone events of a master waybill are likewise returned in `created_at` ascending order.

### 2.4. Common Resource Properties and the Audit Trail

Every primary resource — shipper, flight booking, master waybill, house waybill, screening record, customs entry, rate agreement, and claim — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource's properties.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource. This field is the basis of optimistic concurrency control where §2.5 applies.

The milestone event is the deliberate exception: it is an append-only audit entry and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from milestone events — a recorded milestone is never modified, so there is nothing to version.

Any mutation that the system applies as a side effect — recomputing a booking's consumption, detaching a waybill during a void, bumping a shipper's demerit counter — is a mutation of the affected resource and therefore refreshes that resource's `updated_at` and, where present, increments its `version`, even though no client called an endpoint on that resource directly.

### 2.5. Optimistic Concurrency Control on the Master Waybill

Exactly one write operation in the system is guarded by optimistic concurrency control: consolidating a house waybill into a master waybill. The consolidation request must carry `expected_master_waybill_version`, a non-optional input field holding the `version` of the target master waybill as the caller last observed it. If that value does not equal the master waybill's current `version` — because another consolidation or a deconsolidation has since advanced it, changing the totals and the attached set the caller based its decision on — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is mutated. No other endpoint accepts a version field; clients must not send one elsewhere.

The OCC rejection is evaluated after authentication, role authorization, and resource existence, and before any state-gate, compliance, lane, rate-agreement, or capacity check. A caller holding a stale version therefore learns `ERR_STALE_VERSION` even when the consolidation would also have failed a later check.

### 2.6. Validation Order Across All Endpoints

When several validation rules could reject the same request, the system evaluates them in a fixed priority order so that the surfaced error is deterministic:

1. User context headers — presence of `X-User-ID` and `X-User-Role` and a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization — the caller's role is permitted for this operation, honoring the per-target role map on customs transitions (`ERR_FORBIDDEN_ROLE`).
3. Existence — resource identifiers in the path, then identifiers referenced in the body, validated left to right; the first missing resource produces its specific 404 (`ERR_SHIPPER_NOT_FOUND`, `ERR_FLIGHT_BOOKING_NOT_FOUND`, `ERR_MASTER_WAYBILL_NOT_FOUND`, `ERR_HOUSE_WAYBILL_NOT_FOUND`, `ERR_SCREENING_RECORD_NOT_FOUND`, `ERR_CUSTOMS_ENTRY_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`).
4. Optimistic concurrency — the stale-version check of §2.5 (`ERR_STALE_VERSION`), where applicable.
5. State gates — the target resource is in a legal from-state, expressed through the specific errors `ERR_HWB_NOT_CLEARED`, `ERR_MAWB_NOT_OPEN_FOR_CONSOLIDATION`, `ERR_BOOKING_NOT_OPEN`, `ERR_HWB_NOT_DELIVERED`, `ERR_MEASURED_VOLUME_MISSING`, `ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS`, or the generic `ERR_INVALID_STATE`.
6. Dangerous-goods compliance — known-shipper standing at submit and at consolidation (`ERR_SHIPPER_NOT_KNOWN`).
7. Segregation of duties — the screening resolver is not the submitter (`ERR_SEGREGATION_OF_DUTIES`).
8. Structural and aggregate guards — waybill number and account code uniqueness (`ERR_DUPLICATE_WAYBILL_NUMBER`), tender-window buffering (`ERR_TENDER_WINDOW_CONFLICT`), rate agreement overlap (`ERR_RATE_AGREEMENT_OVERLAP`), tender requires a consolidated waybill (`ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS`), close blocked by open claims (`ERR_OPEN_CLAIMS_EXIST`), one open claim per waybill (`ERR_DUPLICATE_OPEN_CLAIM`), and other malformed-input rejections (`ERR_INVALID_REQUEST`).
9. Lane consistency at consolidation (`ERR_LANE_MISMATCH`).
10. Temporal business rules — an active rate agreement at rating time and claim filing windows (`ERR_NO_ACTIVE_RATE_AGREEMENT`, `ERR_CLAIM_FILING_DEADLINE_PASSED`).
11. Capacity and money caps — booking capacity at consolidation and at tender, claim amounts against liability limits (`ERR_CAPACITY_EXCEEDED`, `ERR_AMOUNT_EXCEEDS_LIABILITY`).

A request failing several rules reports the earliest rule in this ordering that it violates.

### 2.7. Capacity Accounting: Consumption and Utilization

A flight booking represents capacity purchased from an airline: `booked_weight_kg` kilograms and `booked_volume_m3` cubic metres of allotment, both strictly positive. Against that allotment the system tracks `consumed_weight_kg` and `consumed_volume_m3`. Consumption is defined over a precise set: the house waybills attached to this booking's master waybills whose status is not `VOID`, counting only attached waybills in `CONSOLIDATED` or later pre-terminal states — that is, `CONSOLIDATED`, `TENDERED`, or `IN_TRANSIT` — and excluding waybills that have reached `DELIVERED` or been detached or cancelled. The weight contribution of each counted waybill is its `chargeable_weight_kg`; the volume contribution is its `effective_volume_m3`.

The booking's `utilization_pct` is the larger of the two consumption ratios — consumed weight divided by booked weight, consumed volume divided by booked volume — whichever is greater, expressed as a percentage and rounded half-up to two decimal places. All three consumption fields start at zero when the booking is created, and all three are recomputed every time the attached set or any member's rated weight or volume changes: at consolidation, at deconsolidation, at tender, at waybill detach during a void, and at booking cancellation.

### 2.8. Money, Rating, and Precision

All monetary amounts in the system are decimal values expressed to exactly two decimal places using round-half-up, and all monetary values appear in responses as numbers, not strings. Two properties of the rating pipeline are pinned and non-negotiable:

- **Lines round before they sum.** Each charge line on a waybill — freight, fuel surcharge, security fee, spot surcharge — is individually rounded half-up to two decimal places first; the waybill's `total_charge_amount` is then the plain sum of those already-rounded lines. Summing raw components and rounding once at the end is a different, forbidden order: a freight line of 151.52 with a 15 percent fuel surcharge of 22.73 and a flat 10.01 security fee totals 184.26 under per-line rounding but 184.25 under sum-then-round.
- **The fuel and spot surcharges are computed from the rounded freight line**, not from the raw rating result, so the percentage is applied to the value actually billed as freight.

Weight itself is money-adjacent in this domain: chargeable weight is always rounded upward to the next half kilogram — never banker's rounding, never nearest — per the rating rule in §3.5.

### 2.9. The Logical Clock

The server maintains a logical clock that governs every time-dependent rule: booking cutoff auto-close, rate agreement validity windows, and claim filing deadlines. Before any test-driving call, the logical clock reads exactly `2026-08-01T00:00:00Z` — a fixed startup default, never the wall clock. An administrative capability available to all six roles advances the logical clock to a supplied `to_iso8601` instant and returns the new `current_utc`. Advancing the clock eagerly re-evaluates time-driven transitions: every booking still `OPEN` whose `cutoff_utc` is at or before the new time transitions to `CUTOFF_CLOSED` as part of the same call. The same auto-close is also applied lazily whenever a booking is read, so a booking whose cutoff has passed reports `CUTOFF_CLOSED` even if no clock call has occurred since. Once a booking is `CUTOFF_CLOSED`, consolidation into it is refused with `ERR_BOOKING_NOT_OPEN`, though tender of an already-assembled master waybill remains possible per §3.4.

### 2.10. Cross-Resource Cascades

Several operations deliberately mutate more than one resource, and every cascade is applied immediately and atomically — all side effects are visible in the triggering response and in any read issued afterwards.

Cancelling a flight booking is the widest cascade, running three links in order. Link one: every master waybill of the booking in `DRAFT`, `OPEN_FOR_CONSOLIDATION`, or `TENDERED` becomes `VOID`. Link two, caused by each voiding: every house waybill attached to a voided master waybill in `CONSOLIDATED` or `TENDERED` returns to `CLEARED`, detached — its `mawb_id` cleared, every charge line zeroed, the spot flag cleared, its rating basis reset, and the voided master waybill's totals zeroed. Link three, caused by the detachments: the booking's consumption and utilization are recomputed over the waybills that remain attached. The same detach cascade runs, with the same field-level effects, when a single master waybill is voided directly.

The screening rejection cascade is the second structural pattern, and it also runs three links: the waybill whose latest screening record was resolved `REJECTED` moves to `SCREENING_REJECTED`; the owning shipper's `screening_rejection_count` increments by one; and if that increment brings the count to the demerit threshold while the shipper is `KNOWN`, the shipper is automatically suspended per §3.3.

## 3. Business Logic & Workflows

### 3.1. Shippers, Accounts, and Rate Agreements

A `ForwarderOps` agent onboards a customer by registering a shipper account with the company `name` and an `account_code`; the account code must be unique across all shippers, and a duplicate is rejected with `ERR_DUPLICATE_WAYBILL_NUMBER`. A new shipper starts with `known_shipper_status` of `UNVERIFIED` and a `screening_rejection_count` of zero. Known-shipper standing has three values — `UNVERIFIED`, `KNOWN`, and `SUSPENDED` — and it gates everything dangerous: submitting a waybill whose `dg_flag` is true, and later consolidating that waybill, both require the shipper to be `KNOWN` at that moment, failing with `ERR_SHIPPER_NOT_KNOWN` otherwise.

Pricing is per customer and per lane. A `PricingManager` files a rate agreement naming the `shipper_id`, the lane endpoints `origin_code` and `destination_code`, and the commercial terms: `weight_breaks` (a list of tiers, each pairing a `min_weight_kg` with a `rate_per_kg`; the tier thresholds must be distinct and ascending, and at least one tier is required), the `min_charge_amount` floor, the `fuel_surcharge_pct` fraction of freight, the flat `security_fee_amount`, an optional `spot_surcharge_pct` defaulting to zero, and the validity window `valid_from_utc` through `valid_to_utc`. The window start is inclusive and the end exclusive, and the end must be strictly after the start. Windows for the same shipper and lane must not overlap: a new agreement whose half-open window intersects an existing one is rejected with `ERR_RATE_AGREEMENT_OVERLAP`, while touching windows — an existing agreement ending exactly when the new one begins — are allowed. An agreement is active for rating when the logical clock reads at or after its `valid_from_utc` and strictly before its `valid_to_utc`. All existing agreements of a shipper can be listed through the shipper resource.

### 3.2. Procuring Capacity: The Flight Booking

A `CapacityPlanner` procures airline capacity by creating a flight booking with the operating `airline_code`, the `flight_number`, the lane's `origin_code` and `destination_code`, the `scheduled_departure_utc`, and the `cutoff_utc` — the latest moment consolidation into this capacity is accepted, which must be strictly earlier than the scheduled departure. The purchased allotment arrives as `booked_weight_kg` and `booked_volume_m3`, both required to be greater than zero. The booking is born `OPEN`, with consumption and utilization at zero.

A booking's `status` walks a short lifecycle: `OPEN`, then `CUTOFF_CLOSED` once the logical clock reaches the cutoff (§2.9), then `DEPARTED` by automatic bubble-up, or `CANCELLED` at any point before departure. The bubble-up to `DEPARTED` fires only from `CUTOFF_CLOSED` and only when two counts both hold: at least one master waybill of the booking is in `IN_TRANSIT`, `ARRIVED`, `DELIVERED`, or `CLOSED`, and no master waybill of the booking remains in `DRAFT`, `OPEN_FOR_CONSOLIDATION`, or `TENDERED`. `DEPARTED` and `CANCELLED` are terminal.

Cancelling a booking is a `CapacityPlanner` action permitted from either `OPEN` or `CUTOFF_CLOSED`; any other state is rejected with `ERR_INVALID_STATE`. Cancellation triggers the three-link cascade of §2.10 — voiding the booking's non-terminal master waybills, detaching and zeroing their consolidated and tendered waybills, and recomputing booking consumption — all in one atomic operation.

### 3.3. House Waybills, Screening, and the Demerit Ledger

A `ForwarderOps` agent issues a house waybill for a customer by supplying the `shipper_id`, a `hwb_number` unique across all house waybills, the lane endpoints `origin_code` and `destination_code`, the `pieces` count, the actual `gross_weight_kg`, and the shipper-declared `declared_volume_m3`. Pieces, gross weight, and declared volume must each be greater than zero. Three optional commercial fields ride along: `dg_flag` (default false) marks the commodity as dangerous goods; `declared_value_amount` (default zero, never negative) records the shipper's declared value for carriage in USD; and `declared_value_surcharge_paid` (default false) records whether the declared-value surcharge was paid — a choice that later selects the claim liability variant (§3.7). A new waybill is `DRAFT`, its computed charge fields are zero, its `weight_basis` is `UNRATED`, and its `mawb_id` is null.

Submitting a `DRAFT` waybill to screening moves it to `SCREENING`, stamps `submitted_by_user_id` with the caller's `X-User-ID`, and auto-creates the required screening records: always one of `screening_type` `SECURITY`, and additionally one of type `DANGEROUS_GOODS` exactly when the waybill's `dg_flag` is true. Within a single submit the security record is created first and the dangerous-goods record second, with strictly increasing `created_at`. Each new record starts with `result` `PENDING`. If the waybill is dangerous goods and the shipper is not `KNOWN`, submission is refused with `ERR_SHIPPER_NOT_KNOWN`; submitting from any state other than `DRAFT` is `ERR_INVALID_STATE`.

Resolution of a `PENDING` record belongs to a `ComplianceOfficer`, who supplies an `outcome` of `CLEARED` or `REJECTED`; on a rejection the officer records a `rejection_reason`, and in both cases the record's `resolved_by_user_id` is stamped with the resolver's `X-User-ID`. Segregation of duties is enforced here: the resolver's `X-User-ID` must differ from the waybill's `submitted_by_user_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

The waybill's status then bubbles up from its records. The clearance rule looks only at the latest record per required type, judged by `created_at` ordering: when the latest record of every required type — `SECURITY` always, `DANGEROUS_GOODS` exactly when `dg_flag` is set — is `CLEARED`, the waybill moves from `SCREENING` to `CLEARED`. When the latest record of any required type is `REJECTED`, the waybill moves from `SCREENING` to `SCREENING_REJECTED` and the demerit cascade of §2.10 runs: the owning shipper's `screening_rejection_count` increments by one, and when the count after increment reaches three while the shipper is `KNOWN`, the shipper's `known_shipper_status` becomes `SUSPENDED` automatically. The boundary is inclusive — the third rejection suspends, the second does not — and a suspended shipper's future dangerous-goods submissions and consolidations are gated by `ERR_SHIPPER_NOT_KNOWN`.

Rejection is not terminal for the waybill. A `ForwarderOps` agent may recall a waybill from `SCREENING` or `SCREENING_REJECTED` back to `DRAFT` for correction; the existing screening records are retained for audit, and a later re-submission creates fresh records, with clearance always judged on the latest record per type. Cancellation is the other exit: a waybill in `DRAFT`, `SCREENING`, `SCREENING_REJECTED`, or `CLEARED` may be cancelled by `ForwarderOps`, landing in terminal `CANCELLED`; from any other state the request is `ERR_INVALID_STATE`.

Reinstatement of a shipper mirrors verification: a `ComplianceOfficer` may verify an `UNVERIFIED` shipper to `KNOWN`, or reinstate a `SUSPENDED` shipper to `KNOWN`, and reinstatement resets the demerit ledger by setting `screening_rejection_count` back to zero. Calling verification from any other standing is `ERR_INVALID_STATE`.

### 3.4. Consolidation Under the Master Waybill

The master waybill is the consolidation vehicle. A `CapacityPlanner` creates one against a booking by supplying the `booking_id` and an `mawb_number` unique across all master waybills; it starts `DRAFT` with all totals — `total_chargeable_weight_kg`, `total_volume_m3`, `total_freight_amount` — at zero. Opening a `DRAFT` master waybill moves it to `OPEN_FOR_CONSOLIDATION`; opening requires the referenced booking to be `OPEN` (otherwise `ERR_BOOKING_NOT_OPEN`), and opening from any state but `DRAFT` is `ERR_INVALID_STATE`.

Consolidation itself is a `ForwarderOps` action: attaching a house waybill, identified by `hwb_id` in the payload, to an open master waybill. The request must also carry `expected_master_waybill_version` per the OCC contract of §2.5. After the generic gates of §2.6, consolidation enforces this chain of business rules:

- The candidate waybill must be `CLEARED`; anything else fails with `ERR_HWB_NOT_CLEARED`.
- The target master waybill must be `OPEN_FOR_CONSOLIDATION`; otherwise `ERR_MAWB_NOT_OPEN_FOR_CONSOLIDATION`.
- The target's booking must be `OPEN`; otherwise `ERR_BOOKING_NOT_OPEN`. Cutoff-closed capacity no longer accepts new freight.
- The stale-version check of §2.5 must pass, else `ERR_STALE_VERSION`.
- Dangerous goods re-check: if the candidate's `dg_flag` is true, the shipper's `known_shipper_status` must still be `KNOWN` at this moment — standing is verified twice, at submit and again at consolidation — else `ERR_SHIPPER_NOT_KNOWN`.
- Lane consistency: the waybill's `origin_code` and `destination_code` must equal the booking's `origin_code` and `destination_code`, else `ERR_LANE_MISMATCH`.
- A rate agreement must be active for the waybill's shipper and lane at the logical clock, else `ERR_NO_ACTIVE_RATE_AGREEMENT`.
- Capacity: the booking's current `consumed_weight_kg` plus the candidate's chargeable weight must not exceed `booked_weight_kg`, and `consumed_volume_m3` plus the candidate's `effective_volume_m3` must not exceed `booked_volume_m3`; a breach on either dimension fails with `ERR_CAPACITY_EXCEEDED`. The candidate's chargeable weight for this check is the quoted variant of §3.5, computed from `declared_volume_m3`.

A successful consolidation mutates three resources atomically. The waybill: `mawb_id` set to the target, `status` to `CONSOLIDATED`, `weight_basis` to `QUOTED`, `chargeable_weight_kg` computed from declared volume, the spot-surcharge flag decided from the pre-assignment utilization snapshot of §3.5 and then locked, all five charge lines computed via the selected rate agreement, and `rate_agreement_id` stamped with that agreement. The master waybill: totals recomputed and `version` incremented by exactly one. The booking: consumption and utilization recomputed per §2.7.

Deconsolidation is the compensating action, also `ForwarderOps`: removing a waybill that is `CONSOLIDATED` under the named master waybill — the master waybill `id` and the `houseWaybillId` are both identified in the request path — returns it to `CLEARED`, clears `mawb_id` to null, zeroes every charge line and `chargeable_weight_kg`, clears both spot fields, resets `weight_basis` to `UNRATED`, and nulls `rate_agreement_id`. The master waybill's totals are recomputed and its `version` increments by one, and booking consumption is recomputed. The removal is only valid while the waybill is `CONSOLIDATED` and actually attached to the named master waybill; otherwise `ERR_INVALID_STATE`.

A master waybill may be voided by a `CapacityPlanner` from `DRAFT` or `OPEN_FOR_CONSOLIDATION` (otherwise `ERR_INVALID_STATE`), landing in terminal `VOID` and running the detach cascade of §2.10 on any waybills it holds. A master waybill in `TENDERED` can only be voided by the system, as link one of the booking-cancellation cascade. Closing is the happy ending: a `CapacityPlanner` closes a `DELIVERED` master waybill to terminal `CLOSED`, but only when no claim on any attached waybill sits in `FILED`, `UNDER_REVIEW`, `COUNTERED`, or `APPROVED`; open claims block the close with `ERR_OPEN_CLAIMS_EXIST`.

### 3.5. Rating: Chargeable Weight, Tariffs, and the Spot Surcharge

Chargeable weight converts a consignment's bulk into billable kilograms. The dimensional weight is the volume divided by the IATA volumetric divisor of 0.006 cubic metres per kilogram — equivalently, one kilogram per 6000 cubic centimetres. The raw chargeable weight is the greater of the waybill's actual `gross_weight_kg` and that dimensional weight, and the final `chargeable_weight_kg` is the raw value rounded upward to the next half kilogram. The rule exists in two variants differing only in volume source: the `QUOTED` variant, computed at consolidation, uses the shipper's `declared_volume_m3`; the `FINAL` variant, computed at master-waybill tender, uses the warehouse-measured `measured_volume_m3`. Because every downstream charge derives from chargeable weight, a measurement delta between declared and measured volume reprices the entire waybill at tender.

Freight rating applies the IATA lowest-applicable-rate rule against the selected agreement's `weight_breaks`. Consider every tier whose `min_weight_kg` is at most the waybill's chargeable weight. If no tier qualifies, the freight line is the agreement's `min_charge_amount`. Otherwise, for each qualifying tier compute the tier's `rate_per_kg` multiplied by the chargeable weight, take the greater of that product and the `min_charge_amount`, and the freight line is the smallest of those per-tier candidates — a higher weight break with a lower per-kilogram rate therefore wins even when the waybill sits below that break. The result is written to `freight_amount`, rounded half-up to two decimal places.

The remaining charge lines follow the pinned ordering of §2.8: `fuel_surcharge_amount` is the rounded freight line multiplied by the agreement's `fuel_surcharge_pct`, rounded half-up to two decimals; `security_fee_amount` is the agreement's flat `security_fee_amount` copied verbatim; `spot_surcharge_amount` is the rounded freight line multiplied by the agreement's `spot_surcharge_pct`, rounded half-up to two decimals, when the spot flag is set, and zero otherwise; and `total_charge_amount` is the sum of the four rounded lines.

The spot surcharge flag is where utilization feeds back into price, and its evaluation order is pinned to remove the circular dependency between the candidate's charges and the utilization the candidate itself creates. First, take a snapshot of the booking's consumption over house waybills already attached to the booking's non-`VOID` master waybills in `CONSOLIDATED` or `TENDERED` state, excluding the candidate. Second, compute the snapshot utilization exactly as §2.7 defines `utilization_pct`. Third, set `spot_surcharge_applied` to true exactly when the snapshot utilization is at least 85.00 percent — the threshold is inclusive. Fourth, compute the charge lines, including the spot line only when the flag is set. Only then is the candidate attached and the booking's consumption recomputed. The flag is locked at consolidation and is never re-evaluated at tender, even though the FINAL re-rate changes every other charge line.

### 3.6. Tender, Milestones, and Arrival

Tendering hands the assembled consolidation to the airline. A `CapacityPlanner` tenders an `OPEN_FOR_CONSOLIDATION` master waybill by supplying `tender_window_start_utc` and `tender_window_end_utc`; the window end must be strictly after the start, else `ERR_INVALID_REQUEST`, and both are stamped onto the master waybill. Tender is gated by a battery of checks, all enforced: the booking must be `OPEN` or `CUTOFF_CLOSED` — tender survives cutoff even though consolidation does not — else `ERR_BOOKING_NOT_OPEN`; at least one attached waybill must be in `CONSOLIDATED` state, else `ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS`; every attached `CONSOLIDATED` waybill must have `measured_volume_m3` recorded, else `ERR_MEASURED_VOLUME_MISSING`; and the requested window must respect a 30-minute buffer against every other `TENDERED` master waybill on the same booking — a conflict exists exactly when the new window's start falls before an existing window's end plus 30 minutes and the new window's end falls after that existing window's start minus 30 minutes — with conflicts rejected as `ERR_TENDER_WINDOW_CONFLICT`. Finally, tender re-rates every attached `CONSOLIDATED` waybill to its FINAL basis and re-checks capacity with FINAL weights: the booking's recomputed consumption must still fit within `booked_weight_kg` and `booked_volume_m3`, else the tender fails with `ERR_CAPACITY_EXCEEDED`.

Warehouse measurement is a small `ForwarderOps` action with an outsized effect: recording `measured_volume_m3` on a waybill is permitted only while the waybill is `CONSOLIDATED`, before tender. Recording it sets `measured_volume_m3` and recomputes `effective_volume_m3`, which always reads the measured volume when set and falls back to `declared_volume_m3` otherwise.

A successful tender moves the master waybill to `TENDERED` and, for each attached `CONSOLIDATED` waybill: `weight_basis` becomes `FINAL`, `chargeable_weight_kg` is recomputed from the measured volume, all charge lines are recomputed through the same rate agreement, the locked spot flag is left untouched, and the waybill's status becomes `TENDERED`. The master waybill's totals and the booking's consumption are then recomputed from the FINAL values.

From tender onward, transit is narrated by milestone events recorded by `ForwarderOps` against the master waybill. Each event carries an `event_code` — `DEPARTED`, `ARRIVED`, `DELIVERED`, or `EXCEPTION` — the `event_time_utc` at which it physically occurred, an optional `note`, and an `exception_code` from `NONE`, `DAMAGE`, `SHORTAGE`, `DELAY`, or `CUSTOMS_HOLD`. The exception code is required to be non-`NONE` exactly when the event code is `EXCEPTION` and must be `NONE` for every other code; a mismatch is `ERR_INVALID_REQUEST`. Milestones obey a strict rank rule: `DEPARTED` has rank 1 and requires the master waybill at rank 0 (that is, `TENDERED`); `ARRIVED` has rank 2 and requires rank 1; `DELIVERED` has rank 3 and requires rank 2. An event whose rank is not exactly the current rank plus one is still recorded — with `out_of_order` set to true — but causes no transition; `EXCEPTION` events never transition anything. Recording milestones against a `CLOSED` or `VOID` master waybill is rejected with `ERR_INVALID_STATE`.

In-order milestones drive the machine. A `DEPARTED` event moves the master waybill `TENDERED → IN_TRANSIT`, carries every attached `TENDERED` waybill to `IN_TRANSIT`, and re-evaluates the booking's auto-departure bubble-up of §3.2. An `ARRIVED` event moves the master waybill `IN_TRANSIT → ARRIVED`. A `DELIVERED` event moves it `ARRIVED → DELIVERED` and delivers the cargo: every attached `IN_TRANSIT` waybill becomes `DELIVERED` with its `delivered_at_utc` stamped from the milestone's `event_time_utc`. That stamp is what starts the claim filing clock of §3.7. The full milestone history of a master waybill is listable, and recording a milestone returns the created event.

### 3.7. Customs Entries and the Broker Handoff

Customs work runs parallel to the physical consolidation. A `ForwarderOps` agent opens a customs entry on a waybill by supplying an `entry_type` of `INFORMAL`, `CONSUMPTION`, or `TRANSIT`, optionally with a `broker_reference` (which may instead be supplied later, at filing); the waybill must not be `CANCELLED`. The entry is born `PREPARING`, identified by its own `id`, and linked to the waybill whose path it was created under.

From there the entry walks a handoff protocol with segregation between the forwarder and the licensed broker. Handing off a `PREPARING` entry to `HANDED_OFF` is a `ForwarderOps` action and additionally requires the underlying waybill to have cleared screening — specifically, to be in `CLEARED`, `CONSOLIDATED`, `TENDERED`, `IN_TRANSIT`, or `DELIVERED`; otherwise `ERR_HWB_NOT_CLEARED`. Filing a `HANDED_OFF` entry to `FILED` is a `CustomsBroker` action; when the transition payload carries a `broker_reference`, it is recorded onto the entry. From `FILED`, the broker alone reports the authority's decision: advancing to terminal `RELEASED`, or to `REJECTED` with a `rejection_reason` recorded from the payload. A rejected entry is not dead: a `ForwarderOps` agent returns it from `REJECTED` to `PREPARING` for rework, and the cycle begins again. Every transition requires the entry to be in exactly the from-state named here; anything else is `ERR_INVALID_STATE`, and role violations surface as `ERR_FORBIDDEN_ROLE` per §2.1.

### 3.8. Claims, Liability Limits, and Settlement

Once cargo is delivered, a `ForwarderOps` agent may file a claim on the shipper's behalf against a `DELIVERED` waybill, supplying the `hwb_id`, a `claim_type` of `DAMAGE`, `SHORTAGE`, `DELAY`, or `LOSS`, and the `claimed_amount`, which must be greater than zero. Filing against a waybill that is not `DELIVERED` fails with `ERR_HWB_NOT_DELIVERED`.

Two gates govern filing. The filing window runs from the waybill's `delivered_at_utc`: `DAMAGE` and `SHORTAGE` claims must be filed within 14 days of delivery, `DELAY` and `LOSS` claims within 21 days, and filing exactly at the deadline is allowed; a late filing is rejected with `ERR_CLAIM_FILING_DEADLINE_PASSED`. And only one open claim may exist per waybill: if another claim on the same waybill sits in `FILED`, `UNDER_REVIEW`, `COUNTERED`, or `APPROVED`, the filing fails with `ERR_DUPLICATE_OPEN_CLAIM`.

Filing stamps the claim's liability exposure permanently. The `liability_basis` is selected from the waybill's `declared_value_surcharge_paid`: `STANDARD` when unpaid, `DECLARED_VALUE` when paid. Under the `STANDARD` variant, `liability_limit_amount` is the lesser of the `claimed_amount` and the Montreal Convention cap — 22 Special Drawing Rights per kilogram of the waybill's actual `gross_weight_kg`, converted at the fixed rate of 1.35 USD per SDR and rounded half-up to two decimals; the cap is independent of any declared value. Under the `DECLARED_VALUE` variant, the limit is simply the lesser of the `claimed_amount` and the waybill's `declared_value_amount` — so an identical claim on a surcharge-paid waybill yields a different, usually higher, limit. The new claim starts `FILED` with `review_round_count` at zero.

Review belongs to a `ClaimsAdjuster`. Starting review moves a `FILED` claim to `UNDER_REVIEW`. Resolving the review takes an `outcome` with three branches, each carrying equal weight. `APPROVED` requires an `approved_amount` greater than zero and at most the lesser of the `claimed_amount` and the `liability_limit_amount`; the amount is stamped and the claim becomes `APPROVED`. A missing or non-positive amount is `ERR_INVALID_REQUEST`; an amount above the cap is `ERR_AMOUNT_EXCEEDS_LIABILITY`. `DENIED` needs no amount and lands in terminal `DENIED`. `COUNTERED` requires a `counter_amount` greater than zero and at most the `liability_limit_amount` — note the counteroffer is capped by the liability limit alone, not by the claimed amount — with the same error split for missing/non-positive versus over-cap values; the counter amount is stamped and the claim becomes `COUNTERED`. Resolving from any state other than `UNDER_REVIEW` is `ERR_INVALID_STATE`; an optional `reason` may accompany the decision.

A counteroffer returns the ball to the claimant, acting through `ForwarderOps`. Rebutting a `COUNTERED` claim sends it back to `UNDER_REVIEW` and increments `review_round_count` by one — the loop may repeat as many times as the parties need. Accepting the counteroffer instead settles the claim directly: the claim becomes terminal `SETTLED` with `approved_amount` set from the stamped `counter_amount`. Independently, an `APPROVED` claim is settled by the `ClaimsAdjuster`, landing in `SETTLED` at its already-stamped `approved_amount`. Recall from §3.4 that any claim still in `FILED`, `UNDER_REVIEW`, `COUNTERED`, or `APPROVED` blocks closing the parent master waybill — settlement or denial is what unblocks it.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — a shipper, a rate agreement, a flight booking, a master waybill, a house waybill, a customs entry, a claim, or a milestone event — return `201 Created`. Operations that modify an existing resource in place, including all state transitions, consolidations, deconsolidations, resolutions, and the clock-setting capability, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; eagerly auto-closes bookings past cutoff | ForwarderOps, CapacityPlanner, ComplianceOfficer, CustomsBroker, PricingManager, ClaimsAdjuster |
| POST | `/air-freight/shippers` | Register a shipper account (starts UNVERIFIED) | ForwarderOps |
| GET | `/air-freight/shippers/{id}` | Get a shipper | Any declared role |
| POST | `/air-freight/shippers/{id}/verify-known-shipper` | Verify an UNVERIFIED shipper as KNOWN, or reinstate a SUSPENDED shipper (resets demerit count) | ComplianceOfficer |
| GET | `/air-freight/shippers/{id}/rate-agreements` | List rate agreements of a shipper | Any declared role |
| POST | `/air-freight/rate-agreements` | File a rate agreement for a shipper and lane; overlapping validity windows rejected | PricingManager |
| POST | `/air-freight/flight-bookings` | Procure capacity from an airline (booked allotment on one flight) | CapacityPlanner |
| GET | `/air-freight/flight-bookings/{id}` | Get a flight booking (lazily applies cutoff auto-close before responding) | Any declared role |
| POST | `/air-freight/flight-bookings/{id}/cancel` | Cancel a booking; cascades MAWB void, HWB detach, capacity recompute | CapacityPlanner |
| GET | `/air-freight/flight-bookings/{id}/master-waybills` | List master waybills of a booking | Any declared role |
| POST | `/air-freight/master-waybills` | Create a master waybill (DRAFT) against a booking | CapacityPlanner |
| GET | `/air-freight/master-waybills/{id}` | Get a master waybill | Any declared role |
| POST | `/air-freight/master-waybills/{id}/open` | Open a DRAFT master waybill for consolidation | CapacityPlanner |
| POST | `/air-freight/master-waybills/{id}/house-waybills` | Consolidate a CLEARED house waybill (OCC-guarded; rates QUOTED; consumes capacity) | ForwarderOps |
| DELETE | `/air-freight/master-waybills/{id}/house-waybills/{houseWaybillId}` | Remove a CONSOLIDATED house waybill from a master waybill | ForwarderOps |
| POST | `/air-freight/master-waybills/{id}/tender` | Tender the consolidation: measured volumes required, 30-minute window buffer, FINAL re-rate, capacity re-check | CapacityPlanner |
| POST | `/air-freight/master-waybills/{id}/void` | Void a DRAFT or OPEN_FOR_CONSOLIDATION master waybill; detaches consolidated waybills | CapacityPlanner |
| POST | `/air-freight/master-waybills/{id}/close` | Close a DELIVERED master waybill; blocked while any claim is open | CapacityPlanner |
| POST | `/air-freight/master-waybills/{id}/milestone-events` | Record a transit milestone; rank rule governs transitions; out-of-order events recorded without effect | ForwarderOps |
| GET | `/air-freight/master-waybills/{id}/milestone-events` | List milestone events of a master waybill | Any declared role |
| POST | `/air-freight/house-waybills` | Issue a house waybill for a shipper (DRAFT) | ForwarderOps |
| GET | `/air-freight/house-waybills` | List house waybills with optional filters `shipper_id`, `mawb_id`, `status`, `rate_agreement_id` | Any declared role |
| GET | `/air-freight/house-waybills/{id}` | Get a house waybill | Any declared role |
| POST | `/air-freight/house-waybills/{id}/submit` | Submit a DRAFT waybill to security/DG screening; auto-creates screening records | ForwarderOps |
| POST | `/air-freight/house-waybills/{id}/recall` | Recall a waybill from SCREENING or SCREENING_REJECTED back to DRAFT (records retained) | ForwarderOps |
| POST | `/air-freight/house-waybills/{id}/cancel` | Cancel a non-consolidated waybill | ForwarderOps |
| POST | `/air-freight/house-waybills/{id}/measure` | Record the warehouse-measured volume; only while CONSOLIDATED, before tender | ForwarderOps |
| GET | `/air-freight/house-waybills/{id}/screening-records` | List screening records of a waybill, SECURITY before DANGEROUS_GOODS within one submit | Any declared role |
| GET | `/air-freight/house-waybills/{id}/customs-entries` | List customs entries of a waybill | Any declared role |
| GET | `/air-freight/house-waybills/{id}/claims` | List claims of a waybill | Any declared role |
| POST | `/air-freight/screening-records/{id}/resolve` | Resolve a PENDING screening record CLEARED or REJECTED; resolver must differ from submitter | ComplianceOfficer |
| POST | `/air-freight/house-waybills/{id}/customs-entries` | Open a customs entry for a waybill (PREPARING) | ForwarderOps |
| POST | `/air-freight/customs-entries/{id}/transition` | Advance a customs entry; permitted role depends on target_status | ForwarderOps, CustomsBroker |
| POST | `/air-freight/claims` | File a cargo claim against a DELIVERED waybill; stamps liability basis and limit | ForwarderOps |
| GET | `/air-freight/claims/{id}` | Get a claim | Any declared role |
| POST | `/air-freight/claims/{id}/start-review` | Move a FILED claim into review | ClaimsAdjuster |
| POST | `/air-freight/claims/{id}/resolve-review` | Adjuster decision: APPROVED, DENIED, or COUNTERED with amount rules | ClaimsAdjuster |
| POST | `/air-freight/claims/{id}/rebut` | Rebut a counteroffer; claim returns to UNDER_REVIEW | ForwarderOps |
| POST | `/air-freight/claims/{id}/accept-counter` | Accept the counteroffer; settles at the counter amount | ForwarderOps |
| POST | `/air-freight/claims/{id}/settle` | Settle an APPROVED claim at its approved amount | ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SHIPPER_NOT_KNOWN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SHIPPER_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_MASTER_WAYBILL_NOT_FOUND` | 404 Not Found |
| `ERR_HOUSE_WAYBILL_NOT_FOUND` | 404 Not Found |
| `ERR_SCREENING_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMS_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_WAYBILL_NUMBER` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_HWB_NOT_CLEARED` | 409 Conflict |
| `ERR_MAWB_NOT_OPEN_FOR_CONSOLIDATION` | 409 Conflict |
| `ERR_BOOKING_NOT_OPEN` | 409 Conflict |
| `ERR_HWB_NOT_DELIVERED` | 409 Conflict |
| `ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS` | 409 Conflict |
| `ERR_MEASURED_VOLUME_MISSING` | 409 Conflict |
| `ERR_OPEN_CLAIMS_EXIST` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_CLAIM` | 409 Conflict |
| `ERR_TENDER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_RATE_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LANE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_RATE_AGREEMENT` | 422 Unprocessable Entity |
| `ERR_CLAIM_FILING_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_AMOUNT_EXCEEDS_LIABILITY` | 422 Unprocessable Entity |
