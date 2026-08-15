# Ocean Freight NVOCC API — Product Requirements Document

## 1. Introduction

Ocean freight forwarding under an NVOCC (Non-Vessel Operating Common Carrier) license is a business of interlocking legal and financial gates: a shipper cannot book without credit, a bill of lading cannot issue without a qualifying surety bond, a container cannot be released without both customs filings accepted, and a booking cannot be delivered without a released bill of lading and a cleared freight balance. Every commercial commitment a forwarder makes — a rate, a free-day allowance, a bond coverage amount, an insurance premium — is bound to a regulatory framework enforced by the FMC and by CBP, and every failure to honor it carries a measurable financial penalty.

This document specifies the Ocean Freight NVOCC API, a system that governs the full operational lifecycle of a licensed NVOCC forwarder: tariff publication and bonding, voyage scheduling and carrier contract management, shipper credit and invoicing, booking acceptance and consolidation (FCL and LCL), ISF and AMS compliance filing against hard statutory deadlines, bill of lading issuance and release control, demurrage and detention metering, cargo insurance quoting and claim adjudication, and the rollover and blank-sailing contingencies that disrupt the best-laid plans. The API is mounted under `/freight` and serves seven operational roles with strict segregation-of-duties requirements at the compliance, documentation, and claims desks.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, conventions, and invariants that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes seven declared role names — `Shipper`, `BookingCoordinator`, `DocumentationOfficer`, `ComplianceOfficer`, `FinanceController`, `ClaimsAdjuster`, and `OperationsManager` — and treats `Any` as a pseudo-role meaning "every declared role may perform this operation" (it appears only on shared list-and-get endpoints). A request missing either header, carrying an empty or whitespace-only value in either header, or carrying a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed in the endpoint's authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Role identity is bound differently depending on the role. When `X-User-Role` is `Shipper`, `X-User-ID` is the `id` of the acting `Shipper` entity; ownership checks on any resource that references a `Shipper` (a booking's `shipper_id`, a claim's `policy_id` resolved through its policy's booking, and so on) compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Ownership checks apply only to the mutating operations that name them (booking creation by a `Shipper`, booking cancel and roll, bill-of-lading surrender, and claim filing); the shared list-and-get endpoints perform no ownership filtering, so a `Shipper` may read any resource. When `X-User-Role` is `BookingCoordinator`, `DocumentationOfficer`, `ComplianceOfficer`, `FinanceController`, `ClaimsAdjuster`, or `OperationsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on a `Tariff`, `issued_by_user_id` or `released_by_user_id` on a `BillOfLading`, `filed_by_user_id` on a `ComplianceFiling`, or `reviewed_by_user_id` / `approved_by_user_id` on a `CargoClaim` — but does not compare it to any entity's `id`.

Three segregation-of-duties pairs are enforced across desks: the `ComplianceOfficer` who publishes a tariff must differ from the one who created the draft (`published_by_user_id` must differ from `created_by_user_id`); the `DocumentationOfficer` who releases a bill of lading must differ from the one who issued it (`released_by_user_id` must differ from `issued_by_user_id`); and the `ClaimsAdjuster` who approves or denies a claim must differ from the one who started its review (`approved_by_user_id` must differ from `reviewed_by_user_id`). A violation of any of these is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. Unlike entity timestamps (`created_at`, `updated_at`, and domain event stamps such as `stuffed_at` or `issued_at`), which are taken from the logical clock of §2.5, the `api_request_timestamp` is rendered from the server's wall clock.
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

A request to a path that matches no defined route is rejected with `ERR_NOT_FOUND` (HTTP 404); a request to a defined path with an unsupported method is rejected with `ERR_INVALID_REQUEST` (HTTP 405).

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when not provided, has a minimum of 1, and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer, out-of-range, or negative value for either parameter is rejected with `ERR_INVALID_REQUEST` (HTTP 400). All list endpoints return resources sorted by `created_at` in ascending order unless otherwise specified; because many resources share the same logical-clock `created_at`, ties are broken by insertion order (earliest created first). Paginated and non-paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

List endpoints additionally support exact-match equality filtering through query parameters on selected resource fields: shippers by `status`; tariffs by `status`, `origin_port`, `destination_port`; carrier contracts by `status`, `carrier_name`; bonds by `status`; voyages by `status`, `carrier_contract_id`; bookings by `shipper_id`, `voyage_id`, `tariff_id`, `status`; consolidations by `voyage_id`, `cfs_location`, `status`; container assignments by `booking_id`, `consolidation_id`, `status`; bills of lading by `booking_id`, `status`; filings by `booking_id`, `filing_type`, `status`; invoices by `booking_id`, `invoice_type`, `status`; policies by `booking_id`, `status`; and claims by `policy_id`, `booking_id`, `status`. Unrecognized query parameters are ignored.

### 2.4. Common Resource Properties

Every primary resource — `Shipper`, `Tariff`, `CarrierContract`, `SuretyBond`, `Voyage`, `Booking`, `Consolidation`, `ContainerAssignment`, `BillOfLading`, `ComplianceFiling`, `Invoice`, `CargoInsurancePolicy`, and `CargoClaim` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded at first creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): a system-managed counter that starts at 1 on creation and increments by one on every mutation of the resource. The `version` is the anchor for optimistic concurrency control on the writes listed in §2.6.

Any derived-field recompute that writes a new value onto a resource — for example, refreshing `used_weight_kg` on a `Consolidation` after a member is removed, or re-evaluating `available_coverage_cents` on a `SuretyBond` after a penalty accrual — counts as a mutation of that resource and therefore bumps its `version` and refreshes its `updated_at`. Pure reads, including reads that refresh provisional estimates (see §2.7), do not mutate the resource.

### 2.5. The Logical Clock and Lazy Expiry

The system runs on a logical clock, decoupled from wall-clock time, so that long-running maritime lifecycles can be exercised deterministically. Before any operator has advanced it, the logical clock reads exactly `2026-08-01T00:00:00Z` and must not fall back to wall-clock time. An `OperationsManager` may advance the clock by supplying a `to_iso8601` instant; the operation is monotonic, so the supplied instant must be greater than or equal to the current logical time (equality is allowed), and an earlier instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The endpoint returns `200 OK` with an empty `data` object. Everywhere this document says "logical clock" — filing lateness evaluation, demurrage free-time windows, bond expiry, contract expiry, voyage depart/arrive gates — it refers to this controllable clock.

Two resources age lazily against the logical clock. A `SuretyBond` in `ACTIVE` transitions to `EXPIRED` whenever the clock reaches or passes its `effective_to` endpoint, evaluated on read or on any gate check that consults the bond. A `CarrierContract` in `ACTIVE` transitions to `EXPIRED` whenever the clock passes its `service_end`, evaluated on read or on any use of the contract. Advancing the logical clock is itself an event that triggers lazy expiry evaluation for both: any bond whose window has closed and any contract whose `service_end` has passed flip to `EXPIRED` at that moment.

### 2.6. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency control on a parent entity's `version`. Each names a required expected-version field in the request body, and a mismatch with the parent entity's current `version` is rejected with the indicated error and HTTP 412. An expected-version field that is missing or is not an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

- Amending a booking's cargo particulars requires `expected_booking_version` in the request body, carrying the client's last observed `version` of the target `Booking`. If the booking's version has advanced since the client last read it — for example, because another coordinator has just amended the same booking — the request is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412), preventing the writer from overwriting state it has not observed.
- Stuffing an LCL booking into a consolidation requires `expected_consolidation_version`, carrying the client's last observed `version` of the target `Consolidation`. Because a prior stuffing or unstuffing legitimately changes `used_weight_kg` / `used_volume_cbm` and increments the consolidation version, a writer whose capacity view is stale is rejected with `ERR_STALE_CONSOLIDATION_VERSION` (HTTP 412).
- Appending a manual adjustment line to a draft invoice requires `expected_invoice_version`, carrying the client's last observed `version` of the target `Invoice`. A prior adjustment legitimately changed the line set and total, so a writer holding a stale invoice view is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412).

No other endpoint accepts an expected-version field; concurrency protection is applied exactly where listed and nowhere else.

### 2.7. Precision, Rounding, and Monetary Convention

All monetary values are integer cents. Three rounding rules govern every calculation that produces a monetary result:

- Where the spec calls for rounding to 3 decimal places (the revenue-ton derivation), the rule is "round half up" applied to three decimal digits.
- Where a money value is derived from a fractional product — the BAF surcharge, an LCL base amount after the minimum-charge comparison, an LCL terminal handling charge, an insurance insured-value markup or premium multiplication, a deductible percentage, an invoice line amount — the result is rounded to integer cents using "round half up".
- Invoice line rounding is **pinned per line**: each line's `amount_cents` is independently rounded to integer cents via round half up from the product of `quantity` and `unit_rate_cents`, and the invoice `total_cents` is the plain sum of those per-line rounded amounts. Summing raw unrounded products and rounding once at the end is incorrect and yields different cents whenever a line product has a fractional cent.

Day counts used for demurrage and detention are whole-day counts: the system counts complete 24-hour periods between two timestamps via floor division, never fractional days. Volume and weight figures carried on bookings, consolidations, and assignments are 3-decimal-place quantities.

### 2.8. Validation Priority Order

When a single request could fail multiple checks, the system evaluates validation categories in a fixed priority order so that the reported error is deterministic. Lower-numbered priorities run first; the first failing check produces the response. The order is: (1) presence and shape of `X-User-ID` / `X-User-Role` headers; (2) role authorization and shipper ownership; (3) existence of path resources (validated left-to-right) and of foreign keys referenced in the body (such as `voyage_id`, `tariff_id`, `booking_id`, `policy_id`, `consolidation_id`, and `new_voyage_id`); (4) segregation-of-duties checks; (5) request body shape — required fields present, enum members valid, numerics positive where required, conditional fields honored (a `SPOT` rate source must carry `spot_rate_per_unit_cents`; an `FCL` mode must carry `container_type` and `container_count`; an `LCL` mode forbids both); (6) target-resource state permits the operation (voyage `BOOKING_OPEN` for booking/consolidation creation, shipper not `SUSPENDED` for booking creation and confirm, contract `ACTIVE` for voyage creation, and analogous state checks on every state-transition endpoint); (7) regulatory gates — bill of lading release requires both filings `ACCEPTED`, bill of lading issue requires a qualifying bond; (8) commodity compatibility inside a consolidation (HAZMAT and REEFER do not mix); (9) booking referential consistency with the tariff; (10) uniqueness constraints (one filing per booking and type, one FREIGHT invoice per booking, one active bill of lading per booking, one in-flight LCL stuffing per booking); (11) temporal interval rules (window overlap, contract window containment, depart/arrive clock gates, rebook lane match); (12) capacity and count caps (consolidation capacity, rollover cap, amendment cap, consolidation non-empty to close); (13) fiscal gates (credit limit, outstanding balance, overpayment); and finally (14) optimistic-concurrency stale-version checks.

The practical consequence is that a request that fails both a state check and a fiscal gate is reported as the state error, and a request that fails both a role check and a not-found check is reported as the role check. Implementations must honor this order — not just the checks themselves.

### 2.9. Nested Resource Retrieval

Although the resource topology is flat (every collection lives directly under `/freight`), paths still carry resource identifiers, and the system validates them strictly. When an endpoint path contains an identifier, existence is confirmed before any state, role, or business rule runs; a missing identifier yields the corresponding 404 (`ERR_SHIPPER_NOT_FOUND`, `ERR_TARIFF_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_VOYAGE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_CONSOLIDATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_BL_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`). Where a request body references a foreign key, the referenced resource must exist or the same family of 404 errors is returned — a missing `voyage_id` or `new_voyage_id` on a booking write yields `ERR_VOYAGE_NOT_FOUND`, a missing `tariff_id` yields `ERR_TARIFF_NOT_FOUND`, a missing `booking_id` yields `ERR_BOOKING_NOT_FOUND`, a missing `policy_id` yields `ERR_POLICY_NOT_FOUND`, and a missing `consolidation_id` yields `ERR_CONSOLIDATION_NOT_FOUND`.

### 2.10. Hierarchical Consistency and Cascade Semantics

The system maintains cross-entity consistency automatically. When a parent or sibling aggregate undergoes a state change that invalidates dependent resources — a voyage is blanked, a booking is cancelled or rolled, a consolidation is cancelled — the system cascades the change through the dependents without requiring explicit client requests on each. Each cascade step mutates the dependent resource, refreshing its `updated_at` and incrementing its `version`. Conversely, child-state changes that complete a parent's gating condition (every container of an FCL booking gated in, a consolidation tendered, both customs filings accepted with a bill of lading issued) bubble up and may transition the parent automatically. Lazy status re-evaluation on read or on use applies wherever this document describes a status as "lazy". Computed exposures and coverages (shipper credit exposure variants, surety bond available coverage) are recomputed eagerly on every event that affects them, and are also refreshed on read so that a reader always sees the current value.

## 3. Business Logic & Workflows

This section walks the operating rhythm of an NVOCC forwarder: how shippers are registered and credit-managed, how tariffs and contracts are published, how voyages are scheduled and disrupted, how bookings are quoted, confirmed, documented, rolled, and delivered, how LCL freight is consolidated at the container freight station, how bills of lading are issued and released, how customs filings are timed and penalized, how invoices and payments flow, and how cargo insurance and claims are handled.

### 3.1. Shipper Onboarding and Credit Management

A new shipper enters the system when an `OperationsManager` registers it with a `legal_name` and a `credit_limit_cents` expressing the maximum tolerated credit exposure in cents; `credit_limit_cents` must be an integer greater than or equal to zero. The shipper's `credit_terms` may also be supplied at registration and defaults to `PREPAID_ONLY`; the other accepted values are `NET_7` and `NET_30`. Credit terms drive the due date applied to any invoice issued to this shipper: `PREPAID_ONLY` offsets zero days, `NET_7` offsets seven days, and `NET_30` offsets thirty days from the issue timestamp. On creation the shipper's `status` is `ACTIVE`, and both exposure counters — `credit_exposure_posted_cents` and `credit_exposure_forward_cents` — are initialized to zero.

The two exposure counters track distinct fiscal horizons. The **posted** variant is the sum of `balance_cents` over every invoice belonging to this shipper whose status is `ISSUED` or `PARTIALLY_PAID`. The **forward** variant is the posted value plus the sum of `estimated_freight_cents` over every booking of this shipper whose status is one of `CONFIRMED`, `DOCUMENTATION_CLEARED`, `LOADED`, `DEPARTED`, or `ARRIVED` and that does not yet have any FREIGHT invoice in `DRAFT`, `ISSUED`, `PARTIALLY_PAID`, or `PAID`. The forward variant is therefore always greater than or equal to the posted variant, and strictly greater whenever an unbilled in-flight booking exists.

A `FinanceController` may adjust a shipper's credit posture by changing `credit_limit_cents` or `credit_terms` after registration; both fields are optional in the adjustment payload, and a payload supplying neither is accepted as a no-op write that still bumps the shipper's `version`. Both exposure variants are recomputed as a side effect. A `FinanceController` may also manually suspend an `ACTIVE` shipper — transitioning its status from `ACTIVE` to `SUSPENDED` — and may reinstate a `SUSPENDED` shipper, but reinstatement is gated: the shipper's posted exposure must be less than or equal to its `credit_limit_cents`, otherwise the reinstate is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. A state mismatch on either action (suspending a shipper that is not `ACTIVE`, reinstating one that is not `SUSPENDED`) is rejected with `ERR_SHIPPER_INVALID_STATE`.

A suspended shipper may not create new bookings and may not confirm existing quoted ones; either attempt is rejected with `ERR_SHIPPER_SUSPENDED`. Suspension also happens automatically: when an invoice issue leaves the shipper's posted exposure greater than its `credit_limit_cents`, the system transitions the shipper from `ACTIVE` to `SUSPENDED` without further operator action. Note that the reverse is not automatic — a shipper whose posted exposure returns within the limit because a credit-terms adjustment or a payment has been recorded stays `SUSPENDED` until an explicit reinstate.

### 3.2. Tariff Publication and Segregation of Duties

A `ComplianceOfficer` authors a tariff by registering its `tariff_code` (the FMC tariff publication identifier), the `origin_port` and `destination_port` (UN/LOCODE-style codes such as `CNSHA` and `USLAX`), the `commodity_type` (one of `GENERAL`, `REEFER`, or `HAZMAT`), the `mode` (`FCL` or `LCL`), the `rate_per_unit_cents` (an integer greater than or equal to 1), and the effective window as `effective_from` and `effective_to`. For `FCL` tariffs a `container_type` (one of `20GP`, `40GP`, `40HC`, `40RF`) is required; for `LCL` tariffs `container_type` must be omitted. An optional `minimum_charge_cents` (an integer greater than or equal to 0, defaulting to 0) applies only to LCL and is ignored for FCL. The tariff window is **half-open** — the window includes `effective_from` and excludes `effective_to`, so a voyage departing exactly at `effective_to` is not covered. The window must satisfy `effective_from` strictly before `effective_to`, otherwise creation-time or publish-time validation rejects with `ERR_INVALID_REQUEST`.

New tariffs start in `DRAFT`. Publishing a tariff — a `ComplianceOfficer` action — transitions it to `PUBLISHED`, but three preconditions must hold: the tariff must currently be `DRAFT` (otherwise `ERR_TARIFF_INVALID_STATE`); the publisher must differ from the creator (`published_by_user_id` must differ from `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`); and no other `PUBLISHED` tariff may already exist with the identical key tuple — `origin_port`, `destination_port`, `commodity_type`, `mode`, `container_type` — whose half-open window intersects this tariff's window. **Adjacency is not an intersection** for tariffs: if one window ends exactly when another begins, they do not overlap. A window-intersection violation is rejected with `ERR_TARIFF_WINDOW_OVERLAP`.

The publish action accepts an optional `supersedes_tariff_id`. When supplied, the named tariff — which must currently be `PUBLISHED` (otherwise `ERR_TARIFF_INVALID_STATE`) and share the same key tuple (otherwise `ERR_TARIFF_MISMATCH`) — automatically transitions from `PUBLISHED` to `SUPERSEDED` as the new tariff publishes; a supersede target that does not exist is rejected with `ERR_TARIFF_NOT_FOUND`. The tariff named by `supersedes_tariff_id` is exempt from the window-overlap check, so a new tariff may publish over the window of the tariff it supersedes. Independently, a `ComplianceOfficer` may retire a `PUBLISHED` tariff, transitioning it from `PUBLISHED` to `RETIRED`. Retirement does not disturb existing bookings pinned to the tariff, but any attempt to reference the retired tariff in a new booking is rejected with `ERR_TARIFF_NOT_EFFECTIVE`. `SUPERSEDED` and `RETIRED` are terminal.

### 3.3. Carrier Contracts, Service Windows, and Free Time

An `OperationsManager` registers a carrier contract by supplying the `contract_number`, `carrier_name`, `service_lane` (a lane string such as `CNSHA-USLAX`), an array of `container_rates` (each entry pairing a `container_type` with its buy-side `rate_cents`, an integer greater than or equal to 0), the free-time allowances `demurrage_free_days` (default 4) and `detention_free_days` (default 3) — both integers greater than or equal to 0 — a tiered `demurrage_tiers` array, the flat `detention_per_diem_cents` rate (an integer greater than or equal to 0), and the closed service window `service_start` and `service_end`. The contract window is **closed** on both ends — both `service_start` and `service_end` are inclusive — and the start must not be later than the end, otherwise the activation check rejects with `ERR_INVALID_REQUEST`. Each `demurrage_tiers` entry supplies `from_day`, `to_day` (null when the tier is unbounded), and a `per_diem_cents` rate (an integer greater than or equal to 0); day indexes are 1-based chargeable days beyond free time, and the tiers must tile contiguously beginning at `from_day` equal to 1 — each subsequent tier's `from_day` must equal the previous tier's `to_day` plus one, `to_day` must be greater than or equal to `from_day`, and only the final tier may be unbounded (`to_day` null). Malformed rates, allowances, or tier arrays are rejected with `ERR_INVALID_REQUEST`.

New contracts are in `NEGOTIATION`. Activating a contract — an `OperationsManager` action — requires the contract to be `NEGOTIATION` (otherwise `ERR_CONTRACT_INVALID_STATE`) and transitions it to `ACTIVE` only when no other contract with the identical (`carrier_name`, `service_lane`) pair in `ACTIVE` or `SUSPENDED` status has a closed window that intersects this contract's closed window. **Adjacency is an intersection** for contracts (unlike tariffs): a contract whose `service_start` equals an existing contract's `service_end` conflicts with it. An overlap is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`. An `ACTIVE` contract may be suspended (transitioning `ACTIVE` to `SUSPENDED`; any other state rejects with `ERR_CONTRACT_INVALID_STATE`), which blocks new voyage creation against it with `ERR_CONTRACT_NOT_ACTIVE` while leaving existing voyages untouched; a `SUSPENDED` contract may be resumed (again `ERR_CONTRACT_INVALID_STATE` on any other state), which re-runs the window-overlap check against currently `ACTIVE` contracts on the same carrier and lane. A contract whose `service_end` has passed transitions lazily from `ACTIVE` to `EXPIRED` on read or on any use; voyages already scheduled against it remain valid via the pinned contract reference.

### 3.4. Surety Bonds and FMC Compliance

A `ComplianceOfficer` registers a surety bond with its `bond_number` (the FMC NVOCC bond number), the `surety_company`, the `coverage_amount_cents` (an integer greater than or equal to 1), and a half-open effective window `effective_from` / `effective_to`. The bond starts in `INACTIVE` with `available_coverage_cents` equal to `coverage_amount_cents`. Activation — a `ComplianceOfficer` action — requires the bond to be `INACTIVE` (otherwise `ERR_BOND_INVALID_STATE`) and the logical clock to satisfy the window condition: `effective_from` must be less than or equal to the logical clock, and the logical clock must be strictly less than `effective_to` (otherwise `ERR_BOND_NOT_IN_WINDOW`). Activation transitions the bond to `ACTIVE`. When the logical clock reaches or passes `effective_to`, the bond transitions lazily from `ACTIVE` to `EXPIRED` on read or on any gate check; with no qualifying bond available, the bill-of-lading issuance gate fails with `ERR_BOND_COVERAGE_INSUFFICIENT`.

The bond's `available_coverage_cents` is the `coverage_amount_cents` minus the sum of `penalty_amount_cents` over every compliance filing whose `penalty_status` is `ACCRUED` and whose accrual was charged to this bond (each accrual is charged to exactly one selected bond, per §3.10; an accrual recorded with no qualifying bond debits no bond). Accruals and their resolution recompute this figure, as described in §3.10.

### 3.5. Voyage Scheduling, Opening, Departure, Arrival, and Blank Sailings

Voyages are scheduled by an `OperationsManager` against an `ACTIVE` carrier contract. The creation payload names the `vessel_name`, `voyage_number`, the target `carrier_contract_id`, the `origin_port` and `destination_port`, and the estimated times `etd` and `eta`. Two temporal invariants hold: `eta` must be strictly later than `etd` (otherwise `ERR_INVALID_REQUEST`), and the `etd` must lie inside the contract's **closed** service window — that is, on or after `service_start` and on or before `service_end`. A voyage whose `etd` falls outside the contract window is rejected with `ERR_VOYAGE_OUTSIDE_CONTRACT_WINDOW`. On creation the voyage enters `SCHEDULED`, and the system derives two statutory deadlines from the `etd`: the `isf_deadline` is exactly 24 hours before `etd` (ISF 10+2 must be filed 24 hours before loading), and the `ams_deadline` is exactly 48 hours before `etd`.

An `OperationsManager` opens a `SCHEDULED` voyage for booking, transitioning `SCHEDULED` to `BOOKING_OPEN`; a voyage in any other state rejects the open with `ERR_VOYAGE_INVALID_STATE`. From `BOOKING_OPEN` the voyage may depart: departure requires the logical clock to be greater than or equal to `etd` (otherwise `ERR_VOYAGE_NOT_DEPARTABLE`) and transitions the voyage to `DEPARTED`. Departure cascades broadly — bookings in `LOADED` transition to `DEPARTED`; bookings in `CONFIRMED` or `DOCUMENTATION_CLEARED` transition to `ROLLED` with `rolled_reason` set to `MISSED_DEPARTURE` and `rollover_count` incremented by one (a booking whose rollover count would exceed the cap of 2 transitions instead to `CANCELLED`); bookings in `QUOTED` transition directly to `CANCELLED` as the quote lapses; and consolidations on the voyage in `OPEN` or `CLOSED` transition to `CANCELLED` with their member container assignments cancelled, while a consolidation in `TENDERED` rides the voyage and transitions to `DEPARTED` (see §3.9). Each rolled booking cascades further: its bill of lading in `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED` transitions to `VOIDED`; its FREIGHT invoices in `DRAFT` transition to `VOID`; and its container assignments in `STUFFED` or `GATED_IN` transition to `CANCELLED`.

From `DEPARTED` the voyage may arrive: arrival requires the logical clock to be greater than or equal to `eta` (otherwise `ERR_VOYAGE_NOT_ARRIVABLE`) and transitions the voyage to `ARRIVED`. Arrival cascades bookings in `DEPARTED` to `ARRIVED`, container assignments in `LOADED` on those bookings to `DISCHARGED` with `discharged_at` set to the logical clock (this starts the demurrage free-time window), and consolidations in `DEPARTED` to `ARRIVED`. From `ARRIVED` the voyage may be closed — but only when every booking on the voyage is in `DELIVERED` or `CANCELLED`, otherwise the close is rejected with `ERR_VOYAGE_HAS_OPEN_BOOKINGS`. `CLOSED` and `BLANKED` are terminal.

A voyage in `SCHEDULED` or `BOOKING_OPEN` may instead be declared a blank sailing, transitioning directly to `BLANKED`. The blank-sailing cascade mirrors the departure cascade for bookings that have not yet loaded: bookings in `CONFIRMED`, `DOCUMENTATION_CLEARED`, or `LOADED` transition to `ROLLED` with `rolled_reason` set to `BLANK_SAILING` and `rollover_count` incremented by one (again capped at 2, with excesses going to `CANCELLED`); bookings in `QUOTED` are `CANCELLED`; each rolled booking's bill of lading in `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED` is `VOIDED`, its DRAFT FREIGHT invoices are `VOID`, and its container assignments in `STUFFED` or `GATED_IN` are `CANCELLED`. Consolidations on the voyage in `OPEN`, `CLOSED`, or `TENDERED` are `CANCELLED` with their members cancelled. Voided DRAFT invoices drop out of both shipper credit-exposure variants as the recomputation runs.

### 3.6. Booking Quotation, Confirmation, and Amendment

A booking is created either by a `Shipper` acting for itself (the `shipper_id` defaults to the acting `X-User-ID` and the body field is normally omitted; a `Shipper` that does supply `shipper_id` must supply its own id, and a differing value is rejected with `ERR_INSUFFICIENT_PERMISSIONS`) or by a `BookingCoordinator` acting on the shipper's behalf (the `shipper_id` must then appear in the body). The creation payload names the `voyage_id` and the `tariff_id`, declares the `rate_source` as `CONTRACT` or `SPOT`, supplies `spot_rate_per_unit_cents` (an integer greater than or equal to 1) when `SPOT` is declared (forbidden when `CONTRACT`, and stored as null on the resulting booking), declares the `mode` as `FCL` or `LCL`, supplies `container_type` and `container_count` (an integer greater than or equal to 1) for `FCL` (both forbidden for `LCL`, and stored as null on the resulting booking), names the `commodity_type`, reports the `gross_weight_kg` and `volume_cbm` (both strictly positive), and declares the `terms` as `PREPAID` or `COLLECT` — `PREPAID` means payment is due before bill-of-lading release; `COLLECT` means payment is due before delivery.

Creation is gated. The voyage must be `BOOKING_OPEN` (otherwise `ERR_VOYAGE_NOT_OPEN`). The shipper must be `ACTIVE` (otherwise `ERR_SHIPPER_SUSPENDED`). The tariff must be `PUBLISHED` and its half-open window must cover the voyage's `etd` (otherwise `ERR_TARIFF_NOT_EFFECTIVE`). The tariff's `origin_port` and `destination_port` must match the voyage's ports, its `commodity_type` and `mode` must match the booking's, and for `FCL` the booking's `container_type` must equal the tariff's `container_type` — any mismatch is rejected with `ERR_TARIFF_MISMATCH`.

On creation the booking enters `QUOTED` with a server-minted `booking_number` of the form `BK-<seq>`, `rollover_count` initialized to 0, `rolled_reason` null, and `pending_rollover_fee_cents` initialized to 0. Two derived fields are computed immediately. The `chargeable_weight_rt` is the revenue-ton figure: the greater of `gross_weight_kg` divided by 1000 and `volume_cbm` — that is, one revenue ton is one metric tonne or one cubic metre, whichever yields more — rounded half-up to three decimal places. The `estimated_freight_cents` is computed per the ocean-freight-charge rule below and starts the booking's contribution to the shipper's forward exposure.

The ocean-freight-charge rule works as follows. The unit rate is the tariff's `rate_per_unit_cents` when `rate_source` is `CONTRACT`, and the booking's own `spot_rate_per_unit_cents` when `rate_source` is `SPOT` — identical cargo priced under the two variants can land at different totals. For `FCL`, the base is the unit rate multiplied by the `container_count`, and the terminal handling charge is `container_count` times a flat 25000 cents per container. For `LCL`, the base is the greater of the chargeable revenue tons multiplied by the unit rate and the tariff's `minimum_charge_cents`, with the result rounded half-up to integer cents after the comparison, and the terminal handling charge is the chargeable revenue tons multiplied by 1200 cents per revenue ton, rounded half-up. On either mode, the bunker adjustment factor is the base multiplied by ten percent, rounded half-up, and a documentation fee of 7500 cents is added. The total `estimated_freight_cents` is the sum of the base, the bunker adjustment, the terminal handling charge, and the documentation fee. The estimate is recomputed on every amendment of weight, volume, or container count; frozen at confirm; and re-frozen at rebook according to the rollover variant described in §3.7.

Confirmation — a `BookingCoordinator` action — transitions a `QUOTED` booking to `CONFIRMED`. The credit gate runs at confirm: the shipper's forward exposure **excluding this booking's own estimate**, plus this booking's `estimated_freight_cents`, must be less than or equal to the shipper's `credit_limit_cents`; equality is allowed. A failed gate rejects with `ERR_CREDIT_LIMIT_EXCEEDED`. The shipper must still be `ACTIVE` at confirm time (otherwise `ERR_SHIPPER_SUSPENDED`), and the booking must still be `QUOTED` (otherwise `ERR_BOOKING_INVALID_STATE`). On success the estimate is frozen and the shipper's `credit_exposure_forward_cents` now includes this booking.

Amendments of cargo particulars are handled separately by a `BookingCoordinator` while the booking is `QUOTED` or `CONFIRMED`. The amend payload carries `expected_booking_version` (OCC-guarded per §2.6) plus any subset of `gross_weight_kg`, `volume_cbm`, `commodity_type`, `container_count`, and `terms`. A change to weight, volume, or count recomputes `chargeable_weight_rt` and `estimated_freight_cents`; a change to `commodity_type` is re-validated against the pinned tariff (`ERR_TARIFF_MISMATCH` on mismatch). Successful amendment increments the booking's `version` by one.

### 3.7. Rollover, Rebook, and Cancellation

A booking in `CONFIRMED` or `DOCUMENTATION_CLEARED` may be rolled by a `Shipper` (for its own bookings) or a `BookingCoordinator`. The roll action requires `rollover_count` to be below the cap of 2 (otherwise `ERR_ROLLOVER_LIMIT_EXCEEDED`) and a booking state of `CONFIRMED` or `DOCUMENTATION_CLEARED` (otherwise `ERR_BOOKING_INVALID_STATE`). On a successful shipper-initiated roll, the booking transitions to `ROLLED`, `rolled_reason` is set to `SHIPPER_REQUEST`, and `rollover_count` increments by one. The cascade matches the voyage-driven variants: the booking's bill of lading in `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED` transitions to `VOIDED`; its DRAFT FREIGHT invoices transition to `VOID`; and its container assignments in `STUFFED` or `GATED_IN` are `CANCELLED`. For an LCL booking, the consolidation's `used_weight_kg` and `used_volume_cbm` are recomputed; if that consolidation was `CLOSED` and no member assignment remains in `STUFFED`, `GATED_IN`, or `LOADED`, it reopens from `CLOSED` to `OPEN`. The cancel and roll endpoints accept an optional `reason` string for audit; the value is not persisted on the booking resource.

A `ROLLED` booking may be rebooked by a `BookingCoordinator` onto a `new_voyage_id`. The new voyage must exist, must be `BOOKING_OPEN` (otherwise `ERR_VOYAGE_NOT_OPEN`), and must share `origin_port` and `destination_port` with the booking's current voyage — a lane mismatch is rejected with `ERR_VOYAGE_LANE_MISMATCH`. The booking's pinned tariff must still be `PUBLISHED` and its half-open window must cover the new voyage's `etd` (otherwise `ERR_TARIFF_NOT_EFFECTIVE`). The credit gate is re-run against the recomputed estimate (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`). On success the booking's `voyage_id` is replaced with `new_voyage_id`, the booking returns to `CONFIRMED`, `rolled_reason` is reset to null, and `rollover_count` is left unchanged (rebooking does not refund a rollover). The estimate is recomputed according to the rollover variant: when `rolled_reason` is `SHIPPER_REQUEST` the estimate is the fresh quote against the new voyage and `pending_rollover_fee_cents` is increased by a 150000-cent rollover fee, which will surface as a `ROLLOVER_FEE` line on the booking's next FREIGHT invoice; when `rolled_reason` is `BLANK_SAILING` or `MISSED_DEPARTURE` (carrier-caused), the estimate is the **lesser** of the old estimate and the fresh quote — when the fresh quote is not cheaper, the booking keeps its prior frozen estimate and charge decomposition — and no fee accrues.

Cancellation is permitted while the booking is `QUOTED`, `CONFIRMED`, or `DOCUMENTATION_CLEARED`; any other state rejects with `ERR_BOOKING_NOT_CANCELLABLE`. Cancellation is also blocked while any invoice of the booking is `ISSUED` or `PARTIALLY_PAID` with `balance_cents` greater than zero — the rejection is `ERR_OUTSTANDING_BALANCE`. From `QUOTED`, no cancellation fee applies. From `CONFIRMED` or `DOCUMENTATION_CLEARED`, cancellation auto-creates a `CANCELLATION` invoice in `DRAFT` with a single `CANCELLATION_FEE` line at a flat 75000 cents. Either way, the cascade voids the bill of lading in `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED`; voids DRAFT FREIGHT invoices; cancels container assignments in `STUFFED` or `GATED_IN` (with the LCL consolidation recompute and potential reopen described above); cancels any cargo insurance policy in `QUOTED` or `BOUND`; and recomputes the shipper's exposure variants.

### 3.8. Container Assignments, Gate Events, and Demurrage / Detention

Container assignments track the physical life of a box. For an `FCL` booking, a `BookingCoordinator` creates assignments directly with a `booking_id`, an operator-supplied `container_number`, an optional `seal_number`, and the `stuffed_weight_kg` / `stuffed_volume_cbm` measured at stuffing (both strictly positive numbers). The booking must be in `CONFIRMED` or `DOCUMENTATION_CLEARED` (otherwise `ERR_BOOKING_INVALID_STATE`), and the booking may not already hold `container_count` assignments in `STUFFED`, `GATED_IN`, or `LOADED` (otherwise `ERR_CONTAINER_COUNT_EXCEEDED`). Newly created assignments enter `STUFFED` with `consolidation_id` null, `assignment_mode` equal to `FCL`, `stuffed_at` set to the logical clock, the remaining event timestamps (`gated_in_at`, `discharged_at`, `gated_out_at`, `empty_returned_at`) null, and `demurrage_days`, `detention_days`, `demurrage_charge_cents`, `detention_charge_cents`, `provisional_demurrage_cents`, and `provisional_detention_cents` all initialized to zero. LCL bookings never create assignments directly — they acquire them only through the consolidation stuffing flow described in §3.9, where the `container_number` is system-assigned as `<consolidation_number>-BX`, the `seal_number` is left for the consolidation-level seal, the `stuffed_weight_kg` / `stuffed_volume_cbm` are copied from the booking's own `gross_weight_kg` / `volume_cbm`, and the `assignment_mode` is `LCL`.

From `STUFFED`, a `BookingCoordinator` gates the container in: the assignment transitions `STUFFED` to `GATED_IN`, `gated_in_at` is set to the logical clock, and the booking's LOADED gate is re-evaluated for the FCL branch (see below). The assignment must be `STUFFED` (otherwise `ERR_ASSIGNMENT_INVALID_STATE`), and the booking must be in `CONFIRMED` or `DOCUMENTATION_CLEARED` at gate-in (otherwise `ERR_BOOKING_INVALID_STATE`); when both checks would fail, the assignment-state error is reported first.

Booking-level LOADED is a system transition that bubbles up from container events. For an `FCL` booking, the booking transitions from `DOCUMENTATION_CLEARED` to `LOADED` when exactly `container_count` of its assignments are in `GATED_IN` or `LOADED`. For an `LCL` booking, the booking transitions from `DOCUMENTATION_CLEARED` to `LOADED` when its assignment's consolidation reaches `TENDERED`, `DEPARTED`, or `ARRIVED`. Either way, member assignments in `GATED_IN` transition to `LOADED` alongside.

After voyage arrival, assignments in `LOADED` transition to `DISCHARGED` with `discharged_at` set to the logical clock; this starts the demurrage free-time window. A `BookingCoordinator` then gates the container out — a transition from `DISCHARGED` to `GATED_OUT` that stamps `gated_out_at` and freezes the **final** demurrage computation. From `GATED_OUT`, the empty-return action transitions the assignment to `EMPTY_RETURNED`, stamps `empty_returned_at`, and freezes the **final** detention computation. If the sum of `demurrage_charge_cents` and `detention_charge_cents` is greater than zero, empty-return auto-creates a `DEMURRAGE_DETENTION` invoice in `DRAFT` for the booking, with `DEMURRAGE` and `DETENTION` lines (zero-valued lines are skipped) — the `DEMURRAGE` line carries `quantity` 1 and `unit_rate_cents` equal to the demurrage charge, and the `DETENTION` line carries `quantity` equal to `detention_days` and `unit_rate_cents` equal to the contract's `detention_per_diem_cents` — and the shipper's exposure variants are recomputed.

The demurrage and detention rule computes whole-day intervals: the day count between two timestamps is the floor of their difference divided by 24 hours, with no fractional days. Chargeable demurrage days are the whole days between `discharged_at` and `gated_out_at`, minus the contract's `demurrage_free_days`, floored at zero — a stay of exactly the free-day count yields zero chargeable days, and gate-out at the same instant as discharge yields zero. Chargeable detention days are the whole days between `gated_out_at` and `empty_returned_at`, minus the contract's `detention_free_days`, floored at zero. The demurrage charge walks the contract's `demurrage_tiers` in ascending `from_day` order: each tier covers a span equal to the tier's `to_day` minus `from_day` plus one (or, for the unbounded final tier where `to_day` is null, all remaining days), capped by the remaining chargeable days; the tier's `per_diem_cents` is multiplied by the days it covers, the running charge accumulates, and the walk stops when no chargeable days remain. The detention charge is the flat `detention_per_diem_cents` multiplied by the chargeable detention days. The final variant freezes `demurrage_days` and `demurrage_charge_cents` at gate-out and `detention_days` and `detention_charge_cents` at empty-return.

While an assignment is `DISCHARGED` or `GATED_OUT` but not yet `EMPTY_RETURNED`, the system also maintains forward-looking **provisional** figures that refresh on every read: `provisional_demurrage_cents` treats the still-open demurrage interval as closing at the current logical clock (that is, `gated_out_at` is treated as now while the assignment is `DISCHARGED`), and `provisional_detention_cents` does the same for the detention interval while the assignment is `GATED_OUT`. While the assignment is `DISCHARGED` the detention interval has not started, so `provisional_detention_cents` reads as zero; while the assignment is `GATED_OUT` the demurrage interval is already frozen, so `provisional_demurrage_cents` reads as the frozen `demurrage_charge_cents`. In every other state the provisional fields simply report their stored values (zero before any freeze). These provisional figures diverge from the eventual frozen values whenever the real event happens later.

Assignments may be cancelled by cascade (booking cancel or roll, consolidation cancel, voyage blank or depart). Cancellation from `STUFFED` or `GATED_IN` triggers the LCL consolidation recompute — `used_weight_kg` and `used_volume_cbm` are recomputed over the remaining members in `STUFFED`, `GATED_IN`, or `LOADED`, and a `CLOSED` consolidation with zero remaining members reopens to `OPEN`.

### 3.9. LCL Consolidation and Commodity Compatibility

A `BookingCoordinator` opens a consolidation at a container freight station by supplying the `voyage_id`, the `cfs_location`, the `container_type` of the consolidation box, its `max_weight_kg` and `max_volume_cbm` capacities (both strictly positive), and the half-open `stuffing_window_start` / `stuffing_window_end` interval (the end must be strictly after the start, otherwise `ERR_INVALID_REQUEST`). The voyage must be `BOOKING_OPEN` (otherwise `ERR_VOYAGE_NOT_OPEN`). A separate temporal rule guards stuffing-window overlap at a station: another consolidation at the same `cfs_location` in `OPEN`, `CLOSED`, or `TENDERED` whose half-open stuffing window intersects the new window blocks creation with `ERR_STUFFING_WINDOW_OVERLAP`; adjacency is allowed. The new consolidation enters `OPEN` with a server-minted `consolidation_number` of the form `CON-<seq>` and `used_weight_kg` / `used_volume_cbm` initialized to zero.

Stuffing — a `BookingCoordinator` action — adds an LCL booking to an `OPEN` consolidation. The payload carries the `booking_id` and the OCC guard `expected_consolidation_version` (per §2.6, a stale consolidation version rejects with `ERR_STALE_CONSOLIDATION_VERSION`). The booking must have `mode` equal to `LCL` and be in `CONFIRMED` or `DOCUMENTATION_CLEARED` (otherwise `ERR_BOOKING_INVALID_STATE`); the consolidation must be `OPEN` (otherwise `ERR_CONSOLIDATION_INVALID_STATE`). Two capacity-and-commodity gates apply. The **capacity gate** requires the resulting totals to fit: `used_weight_kg` plus the booking's `gross_weight_kg` must be less than or equal to `max_weight_kg`, and `used_volume_cbm` plus the booking's `volume_cbm` must be less than or equal to `max_volume_cbm` — equality is allowed on both axes, but one kilogram or one cubic centimetre over rejects with `ERR_CONSOLIDATION_CAPACITY_EXCEEDED`. The **commodity-mix gate** forbids stuffing a `HAZMAT` booking into a consolidation that already holds a `REEFER` member booking, and vice versa; `GENERAL` mixes with either. A violation is rejected with `ERR_INCOMPATIBLE_CARGO_MIX`. A booking that already holds an LCL assignment in `STUFFED`, `GATED_IN`, or `LOADED` may not be stuffed again (rejected with `ERR_BOOKING_ALREADY_STUFFED`). A successful stuff creates the member assignment per §3.8, recomputes `used_weight_kg` / `used_volume_cbm` over the member set in `STUFFED`, `GATED_IN`, or `LOADED`, increments the consolidation's `version` by one, and returns `201 Created` with the created member assignment (not the consolidation) in the `data` field.

Unstuffing removes a stuffed booking from a consolidation by `booking_id`. The booking must hold a member assignment in this consolidation with status `STUFFED` or `GATED_IN` (otherwise `ERR_ASSIGNMENT_NOT_FOUND`), and the consolidation must be `OPEN` or `CLOSED` (otherwise `ERR_CONSOLIDATION_INVALID_STATE`). The member assignment transitions to `CANCELLED`, `used_weight_kg` / `used_volume_cbm` are recomputed, and a `CLOSED` consolidation left with zero remaining members in `STUFFED`, `GATED_IN`, or `LOADED` automatically reopens to `OPEN`. Unstuffing increments the consolidation's `version` by one and returns the updated consolidation in the `data` field.

A `BookingCoordinator` closes a non-empty `OPEN` consolidation: the close requires at least one member assignment in `STUFFED` or `GATED_IN` (otherwise `ERR_CONSOLIDATION_EMPTY`) and transitions the consolidation from `OPEN` to `CLOSED`. Tendering — also a `BookingCoordinator` action — moves a `CLOSED` consolidation to `TENDERED` when its voyage is `BOOKING_OPEN` (otherwise `ERR_VOYAGE_INVALID_STATE`); tendering transitions every member assignment from `STUFFED` to `GATED_IN` and re-evaluates the LOADED gate for every member booking on the LCL branch. From `TENDERED` the consolidation rides the voyage cascades: voyage departure transitions it to `DEPARTED`, and voyage arrival transitions it to `ARRIVED`. Cancellation is allowed from `OPEN`, `CLOSED`, or `TENDERED` — manually by a `BookingCoordinator` at any time, or automatically by the voyage cascades (the blank cascade cancels `OPEN`, `CLOSED`, and `TENDERED` consolidations; the departure cascade cancels only `OPEN` and `CLOSED` consolidations, since a `TENDERED` consolidation rides the voyage to `DEPARTED`) — and transitions every member assignment in `STUFFED` or `GATED_IN` to `CANCELLED` with `used_weight_kg` and `used_volume_cbm` reset to zero. `ARRIVED` and `CANCELLED` are terminal for a consolidation.

### 3.10. Customs Filings, Statutory Deadlines, and Penalty Accrual

For every booking that will load, two customs filings must be made: an ISF filing (the 10+2 importer security filing) and an AMS manifest filing. A `ComplianceOfficer` creates a filing by naming the `booking_id` and the `filing_type` — `ISF` or `AMS`. The booking must be in `CONFIRMED`, `DOCUMENTATION_CLEARED`, `LOADED`, or `DEPARTED` (otherwise `ERR_BOOKING_INVALID_STATE`). At most one filing may exist per (`booking_id`, `filing_type`); a duplicate is rejected with `ERR_FILING_EXISTS`. On creation the filing enters `PENDING`, the `filed_by_user_id` is stamped from `X-User-ID`, and the `deadline_at` is **frozen** as a snapshot: for an `ISF` filing it equals the voyage's `isf_deadline` (24 hours before `etd`); for an `AMS` filing it equals the voyage's `ams_deadline` (48 hours before `etd`).

Submission — a `ComplianceOfficer` action — transitions a `PENDING` or `REJECTED` filing to `SUBMITTED`; a filing in any other state rejects the submission with `ERR_FILING_INVALID_STATE`. The booking must still be in `CONFIRMED`, `DOCUMENTATION_CLEARED`, `LOADED`, or `DEPARTED` (otherwise `ERR_BOOKING_INVALID_STATE`), and the voyage must not be `BLANKED` (otherwise `ERR_VOYAGE_INVALID_STATE`). The `submitted_at` is stamped with the logical clock (and refreshed on any resubmission from `REJECTED`), and `is_late` is recomputed against the frozen `deadline_at`. The lateness rule is strict: a submission is late only when `submitted_at` is strictly greater than `deadline_at`; a submission exactly at the deadline is on time. When a submission is late and the filing's `penalty_status` is still `NONE`, the penalty accrues: `penalty_amount_cents` is set to 500000 cents for an `ISF` filing and 300000 cents for an `AMS` filing, and `penalty_status` transitions from `NONE` to `ACCRUED`. The accrual debits the available coverage of the bond selected as: `ACTIVE`, with a window covering the logical clock, and with the earliest `created_at` among qualifying bonds; if no bond qualifies, the accrual is recorded on the filing only and debits nothing. An on-time submission carries `penalty_amount_cents` of zero. A filing already `ACCRUED` stays `ACCRUED` on resubmission — no double accrual — and a resubmission that lands on time leaves the penalty status unchanged: penalties are never retroactively waived.

Once submitted, a filing awaits the customs authority's response. A `ComplianceOfficer` records the response with an `outcome` of `ACCEPTED` or `REJECTED`. `ACCEPTED` transitions the filing from `SUBMITTED` to `ACCEPTED`; `REJECTED` transitions it to `REJECTED`. Either transition requires the filing to currently be `SUBMITTED` (otherwise `ERR_FILING_INVALID_STATE`). Acceptance re-evaluates the booking's DOCUMENTATION_CLEARED gate described in §3.11. An accrued penalty may later be resolved by a `ComplianceOfficer` with a `resolution` of `PAID` or `WAIVED`; the resolution transitions `penalty_status` from `ACCRUED` to `PAID` or `WAIVED`, removing the accrual from the charged bond's `available_coverage_cents` recomputation. A resolve attempt on a filing whose `penalty_status` is not `ACCRUED` is rejected with `ERR_FILING_INVALID_STATE`.

### 3.11. Bills of Lading: Issuance, Amendment, Surrender, and Release

A `DocumentationOfficer` drafts a bill of lading for a booking by naming the `booking_id`, the `bl_type` (`HOUSE` or `MASTER`), and the `release_mode` — `ORIGINAL` (paper surrender required), `SEAWAY` (express release), or `TELEX` (surrender at origin). The booking must be in `CONFIRMED`, `DOCUMENTATION_CLEARED`, `LOADED`, `DEPARTED`, or `ARRIVED` (otherwise `ERR_BOOKING_INVALID_STATE`), and there may be at most one non-terminal bill of lading per booking — a booking already holding a bill in `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED` rejects a new draft with `ERR_ACTIVE_BL_EXISTS`. The new bill enters `DRAFT` with a server-minted `bl_number` of the form `BL-<seq>` and `amendment_count` initialized to zero.

Issuance — a `DocumentationOfficer` action — transitions a `DRAFT` bill to `ISSUED`. Two gates guard issuance. First, the booking must be in `CONFIRMED`, `DOCUMENTATION_CLEARED`, `LOADED`, or `DEPARTED` (otherwise `ERR_BOOKING_INVALID_STATE`). Second, the **bond gate** requires the existence of a `SuretyBond` whose `status` is `ACTIVE`, whose window satisfies `effective_from` less than or equal to the logical clock and the logical clock strictly less than `effective_to`, and whose `available_coverage_cents` is at least 75000 cents — a failure is rejected with `ERR_BOND_COVERAGE_INSUFFICIENT`. On success `issued_by_user_id` is stamped from `X-User-ID`, and the booking's DOCUMENTATION_CLEARED gate is re-evaluated: a booking in `CONFIRMED` transitions automatically to `DOCUMENTATION_CLEARED` once it holds one `ACCEPTED` ISF filing, one `ACCEPTED` AMS filing, and a bill of lading in `ISSUED` or `SURRENDERED`. Reverting the bill out of `ISSUED` re-opens that gate.

Amendments cycle the bill through `AMENDMENT_PENDING`. Requesting an amendment — a `DocumentationOfficer` action — requires the bill to be `ISSUED` (otherwise `ERR_BL_INVALID_STATE`) and `amendment_count` to be below the cap of 3 (otherwise `ERR_AMENDMENT_LIMIT_EXCEEDED`); the transition is `ISSUED` to `AMENDMENT_PENDING` with `amendment_count` incremented by one. Reissue returns an `AMENDMENT_PENDING` bill to `DRAFT`; as a side effect, a booking in `DOCUMENTATION_CLEARED` reverts to `CONFIRMED` because the documentation gate is no longer satisfied while no bill is in `ISSUED`.

A shipper surrenders its original bill — only valid when `release_mode` is `ORIGINAL` or `TELEX` (otherwise `ERR_BL_INVALID_STATE`) — transitioning `ISSUED` to `SURRENDERED`. The surrendering `Shipper` must own the booking: the acting `X-User-ID` must equal the booking's `shipper_id`, otherwise `ERR_INSUFFICIENT_PERMISSIONS`. A bill in any other state rejects surrender with `ERR_BL_INVALID_STATE`.

Release — a `DocumentationOfficer` action — has two lawful paths. For a `SEAWAY` bill, the direct path transitions `ISSUED` to `RELEASED`. For an `ORIGINAL` or `TELEX` bill, the release path runs from `SURRENDERED` to `RELEASED`; attempting the direct `ISSUED`-to-`RELEASED` transition on a non-SEAWAY bill is rejected with `ERR_BL_INVALID_STATE`. Either path enforces three preconditions: the releaser's `X-User-ID` must differ from `issued_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`); the booking's ISF and AMS filings must both be `ACCEPTED` (otherwise `ERR_FILINGS_NOT_CLEARED`); and, when the booking's `terms` is `PREPAID`, every non-`VOID` FREIGHT invoice of the booking must be `PAID` — `VOID` invoices are dead and ignored by this gate (otherwise `ERR_OUTSTANDING_BALANCE`). On success `released_by_user_id` is stamped from `X-User-ID`.

Voiding is permitted manually only from `DRAFT` or `AMENDMENT_PENDING`; a manual void of an `ISSUED` or `SURRENDERED` bill is rejected with `ERR_BL_INVALID_STATE`. The system cascades void bills in `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED` to `VOIDED` when the parent booking is cancelled or rolled or when the voyage blanks or departs with the booking rolled. `RELEASED` and `VOIDED` are terminal.

### 3.12. Freight Invoicing, Payments, and Shipper Credit Effects

A `FinanceController` generates the FREIGHT invoice for a booking in `CONFIRMED`, `DOCUMENTATION_CLEARED`, `LOADED`, `DEPARTED`, or `ARRIVED` (otherwise `ERR_BOOKING_INVALID_STATE`). At most one non-`VOID` FREIGHT invoice exists per booking — a FREIGHT invoice left in `VOID` by a cascade does not block generating a fresh one; a second live FREIGHT invoice is rejected with `ERR_INVOICE_EXISTS`. The generation endpoint technically accepts any `invoice_type` of `FREIGHT`, `DEMURRAGE_DETENTION`, or `CANCELLATION` under the same booking-state gate, but the auto-derived line set is built only for `FREIGHT`; a manually generated `DEMURRAGE_DETENTION` or `CANCELLATION` invoice is created with an empty `lines` array (and therefore, with `total_cents` of zero, can never be issued — see the `ERR_INVOICE_EMPTY` rule below). The invoice is created with `invoice_type` equal to `FREIGHT` and enters `DRAFT` with a server-minted `invoice_number` of the form `INV-<seq>`. Its `lines` array is built from the booking's frozen estimate decomposition — the same computation that produced the current `estimated_freight_cents`, not a fresh re-quote — per the ocean-freight-charge rule: an `OCEAN_FREIGHT` line for the base, a `BAF` line for the bunker adjustment, a `THC` line for terminal handling, a `DOC_FEE` line for the documentation fee, plus one `INSURANCE_PREMIUM` line per `BOUND` policy on the booking (see §3.13), plus a `ROLLOVER_FEE` line consuming any `pending_rollover_fee_cents` accrued through shipper-requested rebooks — emitting the line zeroes `pending_rollover_fee_cents`, a mutation of the booking that bumps its `version`. Each line is shaped as `line_type`, `description`, `quantity`, `unit_rate_cents`, and `amount_cents`; the `quantity` / `unit_rate_cents` pairs are: `OCEAN_FREIGHT` — `container_count` × unit rate for `FCL`, `chargeable_weight_rt` × unit rate for `LCL` (or, when the LCL minimum-charge floor bound the base, quantity 1 × the floored base); `BAF` — 1 × the bunker adjustment; `THC` — `container_count` × 25000 for `FCL`, `chargeable_weight_rt` × 1200 for `LCL`; `DOC_FEE` — 1 × 7500; `INSURANCE_PREMIUM` — 1 × the policy's `premium_cents`; `ROLLOVER_FEE` — 1 × the consumed fee. `amount_cents` is the round-half-up product of `quantity` and `unit_rate_cents` per line, and `total_cents` is the plain sum of the rounded line amounts (the pinned per-line rounding rule of §2.7). The `paid_cents` starts at zero, and `balance_cents` is the `total_cents` minus `paid_cents`.

Issuing — a `FinanceController` action — requires the invoice to be `DRAFT` (otherwise `ERR_INVOICE_INVALID_STATE`) and `total_cents` to be strictly greater than zero (otherwise `ERR_INVOICE_EMPTY`). On issue the invoice transitions to `ISSUED`, `issued_at` is stamped with the logical clock, and `due_date` is computed as `issued_at` plus the offset indicated by the shipper's `credit_terms` — zero days for `PREPAID_ONLY`, seven days for `NET_7`, thirty days for `NET_30`. Issuance recomputes the shipper's `credit_exposure_posted_cents` and `credit_exposure_forward_cents`, and if the posted exposure now exceeds the shipper's `credit_limit_cents`, the shipper automatically transitions from `ACTIVE` to `SUSPENDED`.

Payments — recorded by a `FinanceController` — carry an `amount_cents` that must be an integer (otherwise `ERR_INVALID_REQUEST`), strictly greater than zero, and less than or equal to the current `balance_cents`; a violation of the amount bounds is rejected with `ERR_OVERPAYMENT`. The invoice must be `ISSUED` or `PARTIALLY_PAID` (otherwise `ERR_INVOICE_INVALID_STATE`). A payment smaller than the remaining balance transitions the invoice to `PARTIALLY_PAID` (and a further partial payment on an already `PARTIALLY_PAID` invoice is a self-loop back to `PARTIALLY_PAID`); a payment equal to the remaining balance transitions it to `PAID`. Each payment accumulates into `paid_cents` and recomputes the shipper's exposure variants.

Voiding — a `FinanceController` action — is permitted from `DRAFT`, or from `ISSUED` when `paid_cents` is zero; any other state rejects with `ERR_INVOICE_INVALID_STATE`. The system cascades DRAFT FREIGHT invoices to `VOID` when the parent booking is cancelled or rolled or when the voyage blanks or departs with the booking rolled. Either path recomputes the shipper's exposure variants, dropping the voided invoice out of the posted set. `PAID` and `VOID` are terminal.

A `FinanceController` may append a manual adjustment to a `DRAFT` invoice. The payload names a `description`, a `quantity` (any number — negative quantities are permitted), a `unit_rate_cents` (any integer — negative rates are permitted, so downward credit adjustments are expressible), and the OCC guard `expected_invoice_version` (per §2.6, a stale invoice version rejects with `ERR_STALE_INVOICE_VERSION`). The new line has `line_type` `MANUAL_ADJUSTMENT`, its `amount_cents` is rounded per the pinned per-line rule, `total_cents` is recomputed as the sum of rounded lines, and the invoice's `version` increments by one.

### 3.13. Cargo Insurance: Quoting, Binding, and Premium Computation

A `BookingCoordinator` quotes a cargo insurance policy for a booking in `CONFIRMED`, `DOCUMENTATION_CLEARED`, or `LOADED` (otherwise `ERR_BOOKING_INVALID_STATE`). The payload names the `booking_id`, the `coverage_type` — `ALL_RISK`, `WA` (With Average), or `FPA` (Free of Particular Average) — and the declared `cargo_value_cents` (strictly positive). There is no per-booking policy cap: a booking may hold any number of policies in any states. The new policy enters `QUOTED` with a server-minted `policy_number` of the form `POL-<seq>`, and three derived fields are computed in a pinned evaluation order. First, the booking's `chargeable_weight_rt` is taken from the booking's weight and volume. Second, the `freight_base_cents` is a snapshot of the booking's ocean-freight base component only — excluding the bunker adjustment, the terminal handling charge, the documentation fee, and any rollover fee. Third, the `insured_value_cents` is the round-half-up result of multiplying the sum of `cargo_value_cents` and `freight_base_cents` by 1.10 (the CIF-plus-ten-percent markup). Fourth, the `premium_cents` is the greater of a 2500-cent minimum premium and the round-half-up product of `insured_value_cents` and the coverage rate: 0.006 for `ALL_RISK`, 0.004 for `WA`, and 0.0025 for `FPA`. The premium and insured value are frozen at `QUOTED` creation; although the premium later feeds the booking's FREIGHT invoice and the shipper's exposure, the exposure gate never feeds back into the premium computation.

Binding — a `BookingCoordinator` action — transitions a `QUOTED` policy to `BOUND`. The booking must be in `CONFIRMED`, `DOCUMENTATION_CLEARED`, or `LOADED` (otherwise `ERR_BOOKING_INVALID_STATE`); the policy must be `QUOTED` (otherwise `ERR_POLICY_INVALID_STATE`). Once bound, the premium becomes billable: the next FREIGHT invoice of the booking carries an `INSURANCE_PREMIUM` line.

Cancellation is permitted manually while the policy is `QUOTED` or `BOUND` (otherwise `ERR_POLICY_INVALID_STATE`), but a manual cancel is blocked while any claim on this policy is in `FILED`, `UNDER_REVIEW`, or `APPROVED` (rejected with `ERR_CLAIMS_OPEN`). The system cascade that runs on booking cancellation transitions the policy to `CANCELLED` regardless — claims are cascade-denied first, so the open-claims precondition is bypassed on the system path. Separately, when a booking reaches `DELIVERED`, any `BOUND` policy on it transitions automatically to `EXPIRED`. `CANCELLED` and `EXPIRED` are terminal.

### 3.14. Cargo Claims and Settlement

A `Shipper` files a cargo claim against a `BOUND` policy by naming the `policy_id`, the `claim_type` — `DAMAGE`, `LOSS`, `SHORTAGE`, or `DELAY` — the `claimed_amount_cents` (strictly positive), and an optional free-text `description`. The policy must be `BOUND` (otherwise `ERR_POLICY_INVALID_STATE`), and the filing shipper must own the booking referenced by the policy — the policy's `booking_id` must belong to the shipper whose `id` matches `X-User-ID`, otherwise `ERR_INSUFFICIENT_PERMISSIONS`. On this endpoint the ownership check is evaluated after body-shape validation, so a request with a malformed body is rejected with `ERR_INVALID_REQUEST` even when the shipper does not own the policy's booking. There is no per-policy claim cap: a policy may carry any number of claims. The claim enters `FILED` with a server-minted `claim_number` of the form `CLM-<seq>`, `booking_id` denormalized from the policy, `settlement_amount_cents` initialized to zero, `settled_at` null, `reviewed_by_user_id` and `approved_by_user_id` null, and `deductible_cents` already computed and stored at filing time per the deductible rule of the settlement waterfall below (the policy's `insured_value_cents` is frozen, so the value cannot drift before approval).

A `ClaimsAdjuster` starts review, transitioning `FILED` to `UNDER_REVIEW` (the claim must currently be `FILED`, otherwise `ERR_CLAIM_INVALID_STATE`; the policy must be `BOUND`, otherwise `ERR_POLICY_INVALID_STATE`), and `reviewed_by_user_id` is stamped from `X-User-ID`. Approval or denial is also a `ClaimsAdjuster` action, but the segregation-of-duties rule applies: the approving or denying adjuster's `X-User-ID` must differ from `reviewed_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), and the claim must currently be `UNDER_REVIEW` (otherwise `ERR_CLAIM_INVALID_STATE`).

Approval computes and freezes `settlement_amount_cents` according to the claim-settlement waterfall. The `deductible_cents` is determined first (and is in practice already fixed at filing, as described above): for `ALL_RISK` and `WA` coverage the `deductible_cents` is the greater of 50000 cents and the round-half-up product of `insured_value_cents` and 0.01; for `FPA` coverage the `deductible_cents` is the greater of 100000 cents and the round-half-up product of `insured_value_cents` and 0.02. The settlement then follows the waterfall: if `claim_type` is `DELAY`, the settlement is zero — consequential loss is excluded on every coverage; otherwise, if `coverage_type` is `FPA` and `claim_type` is `DAMAGE` or `SHORTAGE`, the settlement is zero — FPA covers total loss only, so partial losses pay nothing regardless of the claimed amount; otherwise, the settlement is the greater of zero and the smaller of `claimed_amount_cents` and `insured_value_cents` minus the deductible. Denial sets `settlement_amount_cents` to zero. Both approval and denial stamp `approved_by_user_id` from the acting adjuster's `X-User-ID`.

Settlement — a `FinanceController` action — transitions an `APPROVED` claim to `SETTLED` (any other state rejects with `ERR_CLAIM_INVALID_STATE`) and stamps `settled_at` with the logical clock. `DENIED` and `SETTLED` are terminal.

### 3.15. Delivery and Final Handoff

The last transition in a booking's life is delivery. A `BookingCoordinator` may deliver a booking in `ARRIVED` (any other state rejects with `ERR_BOOKING_INVALID_STATE`). Two preconditions must hold. The booking must hold a bill of lading in `RELEASED` (otherwise `ERR_BL_NOT_RELEASED`). And if the booking's `terms` is `COLLECT`, every non-`VOID` FREIGHT invoice of the booking must be `PAID` — `VOID` invoices are ignored by this gate (otherwise `ERR_OUTSTANDING_BALANCE`) — a `PREPAID` booking has already cleared this gate at bill release. On success the booking transitions from `ARRIVED` to `DELIVERED`, and any `BOUND` cargo insurance policy on the booking transitions automatically to `EXPIRED`. `DELIVERED` and `CANCELLED` are the booking's terminal states.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition and payment-recording actions — return `200 OK`. The clock-advance endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/freight/_clock/set_current_utc` | Advance the logical clock (monotonic) | OperationsManager |
| POST   | `/freight/shippers` | Register a shipper with credit terms | OperationsManager |
| GET    | `/freight/shippers` | List shippers | Any |
| GET    | `/freight/shippers/{shipperId}` | Get a shipper (exposures recomputed on read) | Any |
| PATCH  | `/freight/shippers/{shipperId}/credit-terms` | Adjust credit limit and/or terms | FinanceController |
| POST   | `/freight/shippers/{shipperId}/suspend` | Manually suspend a shipper | FinanceController |
| POST   | `/freight/shippers/{shipperId}/reinstate` | Reinstate a suspended shipper | FinanceController |
| POST   | `/freight/tariffs` | Create a DRAFT tariff record | ComplianceOfficer |
| GET    | `/freight/tariffs` | List tariffs | Any |
| GET    | `/freight/tariffs/{tariffId}` | Get a tariff | Any |
| POST   | `/freight/tariffs/{tariffId}/publish` | Publish a tariff (SoD: publisher != creator) | ComplianceOfficer |
| POST   | `/freight/tariffs/{tariffId}/retire` | Retire a published tariff | ComplianceOfficer |
| POST   | `/freight/carrier-contracts` | Create a carrier contract in NEGOTIATION | OperationsManager |
| GET    | `/freight/carrier-contracts` | List carrier contracts | Any |
| GET    | `/freight/carrier-contracts/{contractId}` | Get a carrier contract | Any |
| POST   | `/freight/carrier-contracts/{contractId}/activate` | Activate a contract (closed-window overlap check) | OperationsManager |
| POST   | `/freight/carrier-contracts/{contractId}/suspend` | Suspend an active contract | OperationsManager |
| POST   | `/freight/carrier-contracts/{contractId}/resume` | Resume a suspended contract (re-runs overlap check) | OperationsManager |
| POST   | `/freight/surety-bonds` | Register an NVOCC surety bond (INACTIVE) | ComplianceOfficer |
| GET    | `/freight/surety-bonds` | List bonds | Any |
| GET    | `/freight/surety-bonds/{bondId}` | Get a bond (available coverage recomputed on read) | Any |
| POST   | `/freight/surety-bonds/{bondId}/activate` | Activate a bond (clock must be inside its half-open window) | ComplianceOfficer |
| POST   | `/freight/voyages` | Create a voyage against an ACTIVE contract | OperationsManager |
| GET    | `/freight/voyages` | List voyages | Any |
| GET    | `/freight/voyages/{voyageId}` | Get a voyage | Any |
| POST   | `/freight/voyages/{voyageId}/open-for-booking` | Open a voyage for bookings | OperationsManager |
| POST   | `/freight/voyages/{voyageId}/depart` | Depart a voyage (clock >= etd) | OperationsManager |
| POST   | `/freight/voyages/{voyageId}/arrive` | Arrive a voyage (clock >= eta) | OperationsManager |
| POST   | `/freight/voyages/{voyageId}/close` | Close an arrived voyage once all bookings are terminal | OperationsManager |
| POST   | `/freight/voyages/{voyageId}/blank` | Declare a blank sailing | OperationsManager |
| POST   | `/freight/bookings` | Create a booking (QUOTED) | Shipper, BookingCoordinator |
| GET    | `/freight/bookings` | List bookings | Any |
| GET    | `/freight/bookings/{bookingId}` | Get a booking | Any |
| PATCH  | `/freight/bookings/{bookingId}` | Amend cargo particulars (OCC-guarded) | BookingCoordinator |
| POST   | `/freight/bookings/{bookingId}/confirm` | Confirm a quoted booking | BookingCoordinator |
| POST   | `/freight/bookings/{bookingId}/cancel` | Cancel a booking | Shipper, BookingCoordinator |
| POST   | `/freight/bookings/{bookingId}/roll` | Shipper-initiated rollover | Shipper, BookingCoordinator |
| POST   | `/freight/bookings/{bookingId}/rebook` | Rebook a ROLLED booking onto a same-lane voyage | BookingCoordinator |
| POST   | `/freight/bookings/{bookingId}/deliver` | Deliver an ARRIVED booking | BookingCoordinator |
| POST   | `/freight/consolidations` | Open a CFS consolidation | BookingCoordinator |
| GET    | `/freight/consolidations` | List consolidations | Any |
| GET    | `/freight/consolidations/{consolidationId}` | Get a consolidation | Any |
| POST   | `/freight/consolidations/{consolidationId}/stuff` | Stuff an LCL booking into the consolidation (OCC-guarded) | BookingCoordinator |
| POST   | `/freight/consolidations/{consolidationId}/unstuff` | Remove a stuffed booking from the consolidation | BookingCoordinator |
| POST   | `/freight/consolidations/{consolidationId}/close` | Close a non-empty OPEN consolidation | BookingCoordinator |
| POST   | `/freight/consolidations/{consolidationId}/tender` | Tender a CLOSED consolidation to the carrier | BookingCoordinator |
| POST   | `/freight/consolidations/{consolidationId}/cancel` | Cancel an OPEN/CLOSED/TENDERED consolidation | BookingCoordinator |
| POST   | `/freight/container-assignments` | Create an FCL container assignment | BookingCoordinator |
| GET    | `/freight/container-assignments` | List container assignments | Any |
| GET    | `/freight/container-assignments/{assignmentId}` | Get an assignment (provisional D&D refreshed on read) | Any |
| POST   | `/freight/container-assignments/{assignmentId}/gate-in` | Gate in a stuffed container | BookingCoordinator |
| POST   | `/freight/container-assignments/{assignmentId}/gate-out` | Gate out a discharged container (freezes final demurrage) | BookingCoordinator |
| POST   | `/freight/container-assignments/{assignmentId}/empty-return` | Return the empty container (freezes final detention, auto-creates D&D invoice) | BookingCoordinator |
| POST   | `/freight/bill-of-lading` | Create a DRAFT B/L for a booking | DocumentationOfficer |
| GET    | `/freight/bill-of-lading` | List bills of lading | Any |
| GET    | `/freight/bill-of-lading/{blId}` | Get a B/L | Any |
| POST   | `/freight/bill-of-lading/{blId}/issue` | Issue a DRAFT B/L (bond gate) | DocumentationOfficer |
| POST   | `/freight/bill-of-lading/{blId}/request-amendment` | Start an amendment cycle (cap 3) | DocumentationOfficer |
| POST   | `/freight/bill-of-lading/{blId}/reissue` | Return an AMENDMENT_PENDING B/L to DRAFT | DocumentationOfficer |
| POST   | `/freight/bill-of-lading/{blId}/surrender` | Shipper surrenders original B/L | Shipper |
| POST   | `/freight/bill-of-lading/{blId}/release` | Release a B/L (SoD: releaser != issuer) | DocumentationOfficer |
| POST   | `/freight/bill-of-lading/{blId}/void` | Void a DRAFT or AMENDMENT_PENDING B/L | DocumentationOfficer |
| POST   | `/freight/compliance-filings` | Create a compliance filing (ISF or AMS) | ComplianceOfficer |
| GET    | `/freight/compliance-filings` | List filings | Any |
| GET    | `/freight/compliance-filings/{filingId}` | Get a filing | Any |
| POST   | `/freight/compliance-filings/{filingId}/submit` | Submit a PENDING or REJECTED filing | ComplianceOfficer |
| POST   | `/freight/compliance-filings/{filingId}/record-response` | Record the customs authority response | ComplianceOfficer |
| POST   | `/freight/compliance-filings/{filingId}/resolve-penalty` | Resolve an accrued penalty (PAID or WAIVED) | ComplianceOfficer |
| POST   | `/freight/invoices` | Generate the FREIGHT invoice for a booking | FinanceController |
| GET    | `/freight/invoices` | List invoices | Any |
| GET    | `/freight/invoices/{invoiceId}` | Get an invoice (lines embedded) | Any |
| POST   | `/freight/invoices/{invoiceId}/issue` | Issue a DRAFT invoice | FinanceController |
| POST   | `/freight/invoices/{invoiceId}/payments` | Record a payment | FinanceController |
| POST   | `/freight/invoices/{invoiceId}/void` | Void a DRAFT or zero-paid ISSUED invoice | FinanceController |
| POST   | `/freight/invoices/{invoiceId}/adjustments` | Append a MANUAL_ADJUSTMENT line (OCC-guarded) | FinanceController |
| POST   | `/freight/insurance-policies` | Quote a cargo insurance policy | BookingCoordinator |
| GET    | `/freight/insurance-policies` | List policies | Any |
| GET    | `/freight/insurance-policies/{policyId}` | Get a policy | Any |
| POST   | `/freight/insurance-policies/{policyId}/bind` | Bind a quoted policy | BookingCoordinator |
| POST   | `/freight/insurance-policies/{policyId}/cancel` | Cancel a QUOTED or BOUND policy | BookingCoordinator |
| POST   | `/freight/claims` | File a cargo claim against a BOUND policy | Shipper |
| GET    | `/freight/claims` | List claims | Any |
| GET    | `/freight/claims/{claimId}` | Get a claim | Any |
| POST   | `/freight/claims/{claimId}/start-review` | Start adjuster review | ClaimsAdjuster |
| POST   | `/freight/claims/{claimId}/approve` | Approve a claim (SoD: approver != reviewer) | ClaimsAdjuster |
| POST   | `/freight/claims/{claimId}/deny` | Deny a claim (SoD: denier != reviewer) | ClaimsAdjuster |
| POST   | `/freight/claims/{claimId}/settle` | Pay out an approved claim | FinanceController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPPER_NOT_FOUND` | 404 Not Found |
| `ERR_TARIFF_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_BOND_NOT_FOUND` | 404 Not Found |
| `ERR_VOYAGE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_CONSOLIDATION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BL_NOT_FOUND` | 404 Not Found |
| `ERR_FILING_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_VOYAGE_NOT_OPEN` | 409 Conflict |
| `ERR_SHIPPER_SUSPENDED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_BOOKING_INVALID_STATE` | 409 Conflict |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_BL_INVALID_STATE` | 409 Conflict |
| `ERR_BL_NOT_RELEASED` | 409 Conflict |
| `ERR_INVOICE_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_EMPTY` | 409 Conflict |
| `ERR_FILING_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_POLICY_INVALID_STATE` | 409 Conflict |
| `ERR_CONSOLIDATION_INVALID_STATE` | 409 Conflict |
| `ERR_CONTRACT_INVALID_STATE` | 409 Conflict |
| `ERR_TARIFF_INVALID_STATE` | 409 Conflict |
| `ERR_BOND_INVALID_STATE` | 409 Conflict |
| `ERR_BOND_NOT_IN_WINDOW` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_VOYAGE_INVALID_STATE` | 409 Conflict |
| `ERR_SHIPPER_INVALID_STATE` | 409 Conflict |
| `ERR_VOYAGE_HAS_OPEN_BOOKINGS` | 409 Conflict |
| `ERR_FILINGS_NOT_CLEARED` | 409 Conflict |
| `ERR_BOND_COVERAGE_INSUFFICIENT` | 409 Conflict |
| `ERR_INCOMPATIBLE_CARGO_MIX` | 422 Unprocessable Entity |
| `ERR_CLAIMS_OPEN` | 409 Conflict |
| `ERR_TARIFF_NOT_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_TARIFF_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FILING_EXISTS` | 409 Conflict |
| `ERR_INVOICE_EXISTS` | 409 Conflict |
| `ERR_ACTIVE_BL_EXISTS` | 409 Conflict |
| `ERR_BOOKING_ALREADY_STUFFED` | 409 Conflict |
| `ERR_TARIFF_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STUFFING_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_VOYAGE_OUTSIDE_CONTRACT_WINDOW` | 422 Unprocessable Entity |
| `ERR_VOYAGE_NOT_DEPARTABLE` | 409 Conflict |
| `ERR_VOYAGE_NOT_ARRIVABLE` | 409 Conflict |
| `ERR_VOYAGE_LANE_MISMATCH` | 409 Conflict |
| `ERR_CONSOLIDATION_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CONSOLIDATION_EMPTY` | 422 Unprocessable Entity |
| `ERR_CONTAINER_COUNT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ROLLOVER_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_OUTSTANDING_BALANCE` | 402 Payment Required |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_STALE_BOOKING_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONSOLIDATION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_INVOICE_VERSION` | 412 Precondition Failed |
