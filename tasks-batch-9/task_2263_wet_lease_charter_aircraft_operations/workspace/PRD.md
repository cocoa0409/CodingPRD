# Wet Lease Charter Operations API — Product Requirements Document

## 1. Introduction

An ACMI wet lease is the aviation industry's answer to a capacity gap: one airline (the **lessor**) supplies an airframe together with its crew, its continuing-airworthiness maintenance and its insurance, and a second airline (the **lessee**) sells the seats. What looks commercially like a simple hourly rental is in practice four interlocking contracts stacked on one another — a regulatory determination about who actually holds operational control, a crew-qualification and duty-limit regime, a maintenance and reliability undertaking, and a block-hour pricing schedule with a minimum guarantee. Today lessors reconcile these four strands in spreadsheets, and the reconciliation fails in predictable places: a lawful airframe substitution strands a crew member who was only rated on the original variant, a revoked insurance certificate leaves legs rostered that may no longer lawfully depart, and a month closes on provisional numbers that nobody can reproduce three weeks later when the lessee disputes the invoice.

This API is the system of record for that whole arrangement. It carries the lease agreement and its responsibility split, the authority docket that rules on operational control, the certificates of insurance that evidence hull and liability cover, the crew qualifications that authorise flying on the lessee's procedures, and every flight leg flown under the lease. From those primitives it derives the money: a monthly utilization window that prorates the minimum guaranteed block hours to the days actually covered by the lease term, credits the lessee for shortfall the lessor caused, charges a tiered premium for overrun, and applies a technical-dispatch-reliability penalty when the lessor misses its reliability undertaking. It then carries the settlement invoice through a segregated prepare/approve/issue cycle, and finally through redelivery — inspection, discrepancy pricing against a maintenance reserve deposit, and the repositioning ferry to the redelivery station.

Two design commitments run through the requirements below. First, **every number is reproducible**: rounding order, tier boundaries, inclusive-versus-exclusive comparisons and evaluation sequence are all pinned, because the whole point of the settlement record is that the lessor and the lessee can independently arrive at the same figure. Second, **every cascade is explicit**: when cover lapses or an airframe goes AOG, the consequences ripple through lease status, leg status, crew exposure and the open month's charge, and the API is required to walk that ripple in full rather than leaving the operator to chase it by hand. All resources are mounted under the `/wetlease` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, envelope shape, pagination, identity and audit fields, arithmetic discipline, concurrency protection, and the cross-cutting operational principles that every workflow in §3 relies upon.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the declared role is not authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `LessorOpsController`, `Lessee`, `RegulatoryAuthority`, `MaintenanceController`, `BillingAdmin`, and `InsuranceUnderwriter`.

- A `LessorOpsController` is the lessor's operations control desk. It drafts leases, files them with the authority, activates them, registers crew members and enrols them in differences training, schedules and closes out flight legs, requests and effectuates airframe substitutions, serves termination and closes the return record.
- A `Lessee` is the charter customer receiving the lift. It consents to or withholds consent from substitutions, reviews the monthly reliability report, disputes a settled month, and reads its own leases' resources.
- A `RegulatoryAuthority` is the civil aviation authority holding the operational-control determination. It records determinations, attaches and clears conditions, and revokes the docket. It cannot touch commercial or fleet resources.
- A `MaintenanceController` is the lessor's technical control desk. It registers airframes, records maintenance and AOG events, files the monthly reliability report, and performs the redelivery inspection.
- A `BillingAdmin` is the block-hour settlement desk. It registers lessees, applies and lifts credit-control suspensions, closes months, prepares, approves, issues and voids invoices, and resolves disputes.
- An `InsuranceUnderwriter` issues and revokes the certificates of insurance evidencing hull and liability cover with the lessee named as additional insured.

**Identity semantics.** When `X-User-Role` is `Lessee`, `X-User-ID` is the `id` of the acting `Lessee` row; ownership checks on any resource that references a `Lessee` compare the `lessee_id` of the `LeaseAgreement` that owns the target resource to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403). This applies to consenting on a substitution, disputing a settled month, reviewing a reliability report, and to every read a `Lessee` performs.

When `X-User-Role` is `LessorOpsController`, `RegulatoryAuthority`, `MaintenanceController`, `BillingAdmin`, or `InsuranceUnderwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `prepared_by_user_id` and `approved_by_user_id` on a `SettlementInvoice`, where the invoice workflow writes the acting `BillingAdmin` identifier — but it never compares such an identifier to any entity's `id`.

**Segregation of duties.** The settlement desk operates under a second-pair-of-eyes rule that is enforced on the opaque identifier itself: the `BillingAdmin` whose `X-User-ID` was recorded as `prepared_by_user_id` on an invoice may not be the `BillingAdmin` who approves it. An attempt to do so is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

### 2.3. Pagination and List Ordering

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum is 100. `offset` is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0. A `limit` that is not an integer within the inclusive range from 1 to 100, or an `offset` that is not an integer of at least 0, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Every list endpoint returns its rows sorted by `created_at` in ascending order unless a specific endpoint states otherwise. List responses report `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope.

Beyond pagination, list endpoints accept foreign-key and status filters that make every relationship in the model reverse-reachable. Airframes may be filtered by `assigned_lease_id`, `status`, `type_designator` and `type_family`. Leases may be filtered by `lessee_id`, `primary_aircraft_id` and `status`. Authority dockets may be filtered by `lease_id` and `determination`; certificates by `lease_id` and `status`. Crew qualifications accept `crew_member_id`, `lease_id` and `status`. Flight legs accept `lease_id`, `aircraft_id`, `captain_id`, `first_officer_id`, `status` and `billing_state`. Substitutions accept `lease_id`, `original_aircraft_id`, `substitute_aircraft_id` and `status`. Utilization periods accept `lease_id`, `status` and `period_month`. Settlement invoices accept `lease_id`, `period_id` and `status`. Reliability reports accept `lease_id`, `aircraft_id`, `status` and `period_month`. Return-condition records accept `lease_id`, `aircraft_id`, `repositioning_leg_id` and `status`. All filters are optional and combine conjunctively.

### 2.4. Resource Identity, Audit Fields and the Logical Clock

Every resource in this system — `Lessee`, `Aircraft`, `CrewMember`, `LeaseAgreement`, `RegulatoryApproval`, `InsuranceCertificate`, `CrewQualification`, `FlightLeg`, `AircraftSubstitution`, `UtilizationPeriod`, `SettlementInvoice`, `ReliabilityReport` and `ReturnCondition` — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, written once when the row is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.

A derived-field recomputation counts as a mutation: when a leg completion rewrites an airframe's counters, or a leg cancellation rewrites a crew member's rolling exposure, or a month close rewrites a period's charge components, the affected resource's `updated_at` is refreshed and its `version` incremented.

**The logical clock.** Every expiry test, rolling-window boundary and coverage check in this system reads a server-held logical UTC clock rather than wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to real wall-clock time. An operator sets it by supplying a `current_utc` instant to `POST /_clock/set_current_utc`; every subsequent evaluation reads the new value. Advancing the clock has consequences: an `ACTIVE` certificate whose `expires_at` now lies in the past moves to `EXPIRED`, a `QUALIFIED` crew qualification whose `checkride_valid_until` date now lies in the past moves to `EXPIRED`, and every crew member's rolling duty and block exposure is recomputed against the new window.

### 2.5. Money, Hours and Rounding Discipline

All monetary amounts in this system are integer counts of US cents; no monetary field is ever a decimal. Hour-denominated quantities are decimal numbers carried to four decimal places, and percentage-denominated reliability figures to two decimal places. Wherever rounding occurs the method is **round half up** — a value exactly on the midpoint rounds away from zero.

Three rounding-order rules are contractual because they change the answer:

1. **Round per leg, then sum.** When a month's credited hours are built from individual legs, each leg's minute contribution is converted to hours and rounded to four decimal places *first*, and the rounded per-leg figures are then added together. This is deliberately not "add the minutes, then divide once": three legs of 100 minutes each yield 1.6667 hours apiece and 5.0001 hours in total, where a single division would have yielded 5.0000 hours.
2. **Round each cents component, then sum.** The base guarantee charge, the shortfall credit, and each of the three overrun tier components are each rounded to whole cents *before* they are added together. There is no single rounding applied to a running decimal total.
3. **Minutes floor down.** Converting an elapsed interval into whole minutes always discards the remaining seconds; a 59-minute-and-59-second interval is 59 minutes.

Airframe hour counters are held to two decimal places, and the substitution eligibility comparison on hours since last heavy check is likewise made at two decimal places. Ranking keys used by the substitute selector are compared exactly, with no rounding.

### 2.6. Optimistic Concurrency Control on Superseding Writes

Two write operations in this system can legitimately supersede work a client may not have seen, and both are therefore protected by a stale-version check rather than by an ordinary state guard.

**Preparing a settlement invoice.** The request that prepares a `SettlementInvoice` must carry `expected_period_version`, a non-optional field holding the `version` of the target `UtilizationPeriod` as the client last read it. If that value does not equal the period's current `version`, the request is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412). The rule exists because the product deliberately permits a later preparation to supersede an earlier `PREPARED` invoice on the same period — for example when the desk switches the `variant` from `PROVISIONAL` to `FINAL` — so a writer holding a stale view of the period would otherwise silently invalidate an invoice it never observed. The check is purely a comparison against `UtilizationPeriod.version`; it is not a timing condition, and it says nothing about how close together two requests arrive.

**Requesting an airframe substitution.** The request that creates an `AircraftSubstitution` must carry `expected_lease_version`, a non-optional field holding the `version` of the target `LeaseAgreement` as the client last read it. A mismatch against the lease's current `version` is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412). A new substitution request legitimately supersedes prior open requests on the same lease and, on a lease whose substitution rights are unilateral, withdraws them outright — so a writer whose view of the lease predates the last airframe re-point, suspension or activation must re-read the lease before it is permitted to supersede anything.

No other endpoint accepts a version field, and no other endpoint performs a version comparison.

### 2.7. Cascade Discipline

A single event in this domain rarely touches a single row. Two cascades in particular are four levels deep, and the server is required to walk them to the bottom within the same request.

The **insurance-lapse cascade** begins when the underwriter revokes cover or the logical clock advances past a certificate's `expires_at`. Level one is the certificate leaving `ACTIVE`. Level two: if no `ACTIVE` certificate remains on the lease, the lease moves from `ACTIVE` to `SUSPENDED` with `suspension_reason` set to `INSURANCE_LAPSED`. Level three: every leg on that lease still in `SCHEDULED` or `DISPATCHED` is cancelled into `CANCELLED_LESSOR`. Level four: each of those cancellations recomputes the rolling duty and block exposure of that leg's captain and first officer, and recomputes the `OPEN` utilization period covering the leg's scheduled off-blocks month.

The **substitution cascade** begins when an approved swap is effectuated. Level one re-points the lease's airframe of record. Level two, caused by that re-point, moves the affected scheduled legs onto the substitute airframe. Level three, caused by each leg re-point, cancels any re-pointed leg whose rostered pilots are not rated on the substitute's exact variant. Level four, caused by each such cancellation, recomputes crew exposure and the open month's charge.

Cascades are forward-looking and never restorative. Reactivating a suspended lease does not un-cancel the legs the suspension cancelled. Lifting a lessee's credit-control suspension does not resurrect a lease submission that was blocked while it was in force.

### 2.8. Validation Order

Because most write endpoints in this system guard against half a dozen distinct failures, the order in which checks run is part of the contract: the first check that fails determines the response, and a later check never masks an earlier one. Checks are evaluated in this sequence.

1. **Authentication** — headers present and `X-User-Role` one of the six declared roles, else `ERR_UNAUTHENTICATED`.
2. **Authorisation** — the acting role is listed for the endpoint, else `ERR_UNAUTHORIZED`.
3. **Request shape** — every required field present, every enum value a declared member, every number within its sign and range constraints, every ISO 8601 datetime and every `YYYY-MM-DD` date parseable, and a leg's `scheduled_in` strictly after its `scheduled_out`; otherwise `ERR_INVALID_REQUEST`.
4. **Pagination bounds** — on every list endpoint, `limit` and `offset` within the bounds of §2.3, else `ERR_INVALID_REQUEST`.
5. **Existence**, resolved in this order and, where a single request carries several identifiers of one kind, left to right in the order the fields are declared in the request: a lessee identifier (`lesseeId` in the path or `lessee_id` in the body) resolving to a `Lessee`, else `ERR_LESSEE_NOT_FOUND`; then every aircraft identifier (`aircraftId`, `primary_aircraft_id`, `original_aircraft_id`, `substitute_aircraft_id`, `aircraft_id`) resolving to an `Aircraft`, else `ERR_AIRCRAFT_NOT_FOUND`; then `leaseId` or `lease_id` resolving to a `LeaseAgreement`, else `ERR_LEASE_NOT_FOUND`; then `crewMemberId`, `crew_member_id`, `captain_id` and `first_officer_id` resolving to `CrewMember` rows, else `ERR_CREW_MEMBER_NOT_FOUND`; then `qualificationId`, else `ERR_QUALIFICATION_NOT_FOUND`; then `approvalId`, else `ERR_APPROVAL_NOT_FOUND`; then `certificateId`, else `ERR_CERTIFICATE_NOT_FOUND`; then `legId` in the path and `repositioning_leg_id` in the body, else `ERR_FLIGHT_LEG_NOT_FOUND`; then `substitutionId`, else `ERR_SUBSTITUTION_NOT_FOUND`; then `periodId` in the path and `period_id` in the body, else `ERR_PERIOD_NOT_FOUND`; then `invoiceId`, else `ERR_INVOICE_NOT_FOUND`; then `reportId`, else `ERR_REPORT_NOT_FOUND`; then `returnId`, else `ERR_RETURN_CONDITION_NOT_FOUND`.
6. **Lessee ownership** — when the acting role is `Lessee`, `X-User-ID` must equal the `lessee_id` of the lease owning the target resource, else `ERR_UNAUTHORIZED`. This applies to consenting on a substitution, disputing a period, reviewing a reliability report, and every read taken by a `Lessee`.
7. **Lessee commercial standing** — the lease's lessee must be `ACTIVE`, else `ERR_LESSEE_SUSPENDED` (HTTP 403). This guards exactly three operations: submitting a lease for approval, activating a lease, and scheduling a flight leg.
8. **Stale-version checks** — first `expected_period_version` on invoice preparation (`ERR_STALE_PERIOD_VERSION`), then `expected_lease_version` on substitution request (`ERR_STALE_LEASE_VERSION`).
9. **State guards**, in this order: lessee state (`ERR_LESSEE_INVALID_STATE`), period readiness for settlement (`ERR_PERIOD_NOT_READY_FOR_SETTLEMENT`), lease state (`ERR_LEASE_INVALID_STATE`), docket determination state (`ERR_APPROVAL_INVALID_STATE`), leg state (`ERR_LEG_INVALID_STATE`), substitution state (`ERR_SUBSTITUTION_INVALID_STATE`), invoice state (`ERR_INVOICE_INVALID_STATE`), period state (`ERR_PERIOD_INVALID_STATE`), return-condition state (`ERR_RETURN_CONDITION_INVALID_STATE`), and finally airframe availability (`ERR_AIRCRAFT_UNAVAILABLE`).
10. **Crew safety**, in this order: type rating and crew standing (`ERR_CREW_NOT_TYPE_RATED`), rolling seven-day duty exposure (`ERR_CREW_DUTY_LIMIT_EXCEEDED`), rolling twenty-eight-day block exposure (`ERR_CREW_BLOCK_LIMIT_EXCEEDED`), and lessee-procedures qualification (`ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES`). Within each of the two exposure checks the captain is tested before the first officer.
11. **Regulatory and insurance gates**, in this order: a live determination on the lease (`ERR_REGULATORY_APPROVAL_MISSING`), the operational-control structure (`ERR_OPERATIONAL_CONTROL_MISMATCH`), conforming cover at the relevant instant (`ERR_INSURANCE_COVERAGE_MISSING`), and the certificate's own limit floors (`ERR_INSURANCE_LIMIT_BELOW_MINIMUM`).
12. **Temporal gates**, in this order: a leg falling inside the lease term (`ERR_LEG_OUTSIDE_LEASE_TERM`), airframe occupancy conflict (`ERR_AIRCRAFT_SCHEDULE_CONFLICT`), and certificate period overlap (`ERR_INSURANCE_PERIOD_OVERLAP`).
13. **Fleet and substitution gates**, in this order: duplicate registration mark (`ERR_DUPLICATE_TAIL_NUMBER`), maintenance-programme alignment (`ERR_MAINTENANCE_PROGRAM_MISALIGNED`), client-specified substitute eligibility (`ERR_SUBSTITUTION_TYPE_MISMATCH`), the consent requirement on effectuation (`ERR_SUBSTITUTION_CONSENT_REQUIRED`), and an empty server-selected candidate pool (`ERR_NO_SUBSTITUTE_AIRCRAFT_AVAILABLE`).
14. **Billing governance**, in this order: an accepted reliability report for the month (`ERR_RELIABILITY_REPORT_NOT_ACCEPTED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and the lessee's credit limit (`ERR_LESSEE_CREDIT_LIMIT_EXCEEDED`).
15. **Redelivery gates**, in this order: open discrepancies blocking closure (`ERR_RETURN_DISCREPANCIES_OPEN`), the repositioning leg's fitness (`ERR_REPOSITIONING_LEG_INCOMPLETE`), and the disputed-amount range on a dispute (`ERR_INVALID_REQUEST`).

Two of these orderings exist specifically so that a specific error surfaces instead of a generic one. An effectuation attempted on a substitution still awaiting lessee consent, on a lease whose substitution rights require that consent, deliberately *passes* the substitution state guard and falls through to the consent gate, so the caller receives `ERR_SUBSTITUTION_CONSENT_REQUIRED` rather than `ERR_SUBSTITUTION_INVALID_STATE`; every other undeclared source state for effectuation — a request still `REQUESTED`, or already `REJECTED`, `EFFECTIVE` or `WITHDRAWN` — and every source state other than awaiting-consent for a consent decision, is reported as `ERR_SUBSTITUTION_INVALID_STATE`. Likewise, a closure attempted on a return record with discrepancies still open deliberately passes the return-condition state guard and falls through to `ERR_RETURN_DISCREPANCIES_OPEN`, whereas a closure attempted while the record is still awaiting inspection, or is already closed, is reported as `ERR_RETURN_CONDITION_INVALID_STATE`.

For nested read paths, identifiers are resolved strictly left to right: a request for the dockets or certificates of a non-existent lease fails on the lease identifier before the sub-collection is ever considered.

### 2.9. Conserved Quantities

Four quantities in this system are defined as functions of other rows, not as free-standing counters, and the server must keep each of them exactly equal to its definition after every operation.

**The lessee receivable.** `Lessee.outstanding_balance_usd_cents` equals the sum of `amount_cents` over every `SettlementInvoice` whose `status` is `ISSUED` and whose lease belongs to that lessee. Invoices in `PREPARED`, `APPROVED` or `VOID` contribute nothing. The balance is maintained incrementally: issuing an invoice adds its `amount_cents`, and voiding an already-issued invoice subtracts the same `amount_cents`, restoring the pre-issue figure exactly. Voiding an invoice that was only `PREPARED` or `APPROVED` leaves the balance untouched. No rounding ever occurs on this quantity.

**The maintenance reserve deposit.** On every lease, `return_deposit_applied_cents` plus `return_deposit_remaining_cents` equals `return_deposit_cents` at all times. A re-inspection recomputes the split from the full original deposit rather than from the surviving remainder, so re-inspecting can never double-draw.

**Rolling crew exposure.** `CrewMember.rolling_duty_minutes_7d` and `CrewMember.rolling_block_minutes_28d` are aggregates over the crew member's own legs, recomputed rather than adjusted. Because cancelled and diverted legs are excluded from the aggregate, cancelling a leg is an exact compensation for having scheduled it.

**Cumulative credited block time.** `LeaseAgreement.lifetime_credited_block_minutes` accumulates the `credited_block_minutes` of the lease's settled months: a period settling adds its figure, and a settled period returning to await settlement because its invoice was voided subtracts the same figure. Completing an individual leg does not itself advance this lease-level total.

### 2.10. Two Independent State Dimensions on a Flight Leg

A `FlightLeg` carries two state fields that evolve independently on the same row, and neither may be inferred from the other.

`status` is the operational dimension: `SCHEDULED`, `DISPATCHED`, `COMPLETED`, `CANCELLED_LESSEE`, `CANCELLED_LESSOR` or `DIVERTED`. A leg is created `SCHEDULED`; `COMPLETED`, `CANCELLED_LESSEE`, `CANCELLED_LESSOR` and `DIVERTED` are terminal.

`billing_state` is the financial dimension: `UNBILLED`, `PROVISIONALLY_BILLED`, `FINALIZED` or `CREDITED`. A leg is created `UNBILLED`. Advancing the operational dimension never touches the financial dimension — dispatching and completing a leg both leave `billing_state` exactly as it was — and advancing the financial dimension never touches `status`.

### 2.11. Dual-Variant Evaluation

Two calculations in this system are computed twice from the same underlying data under two different rules, and the pair of results is meaningful.

The **monthly utilization charge** has a `PROVISIONAL` variant and a `FINAL` variant. The provisional variant is the live, running view of an open month and is recomputed on every leg mutation; the final variant is the closing view, written when the month is closed and rewritten if the month is reopened and closed again. The two variants include different legs and use different per-leg minute figures, so identical leg data yields different credited hours, a different overrun tier split and a different charge. Whichever variant most recently wrote a period's credited and shortfall/overrun fields is recorded in `variant_applied`, which holds either `PROVISIONAL` or `FINAL`.

**Technical dispatch reliability** likewise has a `DEPARTURE_BASIS` variant and a `SCHEDULED_BASIS` variant. Both are always computed and both are always stored on the report, as `tdr_departure_basis_pct` and `tdr_scheduled_basis_pct`; the lease's contractual `reliability_basis` then selects which of the two becomes the binding headline figure in `technical_dispatch_reliability_pct`.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Parties: Lessees, Airframes and Crew

The settlement desk registers a charter customer by supplying its legal `name`, its three-letter ICAO operator designator `icao_code` (exactly three uppercase letters, unique across all lessees), the four-letter `home_base_icao` of its home aerodrome, and the `credit_limit_usd_cents` ceiling the lessor is prepared to carry. A new lessee starts with `status` `ACTIVE` and `outstanding_balance_usd_cents` of 0. Reading a lessee back returns its receivable recomputed from the issued invoices in scope.

Credit control is a two-state cycle on the lessee. A `BillingAdmin` may suspend an `ACTIVE` lessee, moving `status` from `ACTIVE` to `SUSPENDED`, and may reinstate a `SUSPENDED` one, moving it back from `SUSPENDED` to `ACTIVE`. Suspending a lessee that is not `ACTIVE`, or reinstating one that is not `SUSPENDED`, is rejected with `ERR_LESSEE_INVALID_STATE` (HTTP 409). Suspension is deliberately forward-looking: while it holds, no lease of that lessee may be submitted for approval or activated and no new leg may be scheduled — each such attempt is rejected with `ERR_LESSEE_SUSPENDED` — but flying already rostered continues, no already-`ACTIVE` lease is suspended or terminated, and no already-`SCHEDULED` leg is cancelled. Neither leg of the cycle touches `outstanding_balance_usd_cents` or `credit_limit_usd_cents`.

Airframes are registered by technical control with a `tail_number` (the registration mark, five to seven characters, unique across the fleet — a repeat is rejected with `ERR_DUPLICATE_TAIL_NUMBER`), a `type_designator` naming the exact ICAO variant, a `type_family` naming the commercial family that variant belongs to, a certified `seat_count` of at least 1, an `mtow_kg` maximum take-off weight of at least 1, the `maintenance_program_ref` identifying the continuous-airworthiness programme the airframe is enrolled in, and three opening counters: `airframe_hours_total`, `hours_since_last_check` and `cycles_since_last_check`. The two hour counters are non-negative numbers carried to two decimal places and the cycle counter a non-negative integer; each defaults to 0. The distinction between `type_designator` and `type_family` matters throughout: crew type ratings are held against the exact variant designator, whereas substitution eligibility is judged on the family — which is precisely why a lawful substitution can still strand a crew member. A new airframe starts with `status` `AVAILABLE` and `assigned_lease_id` null; that field is non-null exactly while the airframe is the airframe of record for a lease.

Technical control drives the airframe through its availability postures by recording a maintenance event with an `event_type` of `GROUND_SCHEDULED`, `GROUND_AOG`, `RETURN_TO_SERVICE` or `RETIRE`, optionally accompanied by a free-text `note`. A `GROUND_SCHEDULED` event is accepted from `AVAILABLE` or `ASSIGNED` and sets `status` to `IN_MAINTENANCE`; it cancels nothing, so scheduled legs survive but dispatch off that airframe is subsequently refused with `ERR_AIRCRAFT_UNAVAILABLE`. A `GROUND_AOG` event is likewise accepted from `AVAILABLE` or `ASSIGNED` and sets `status` to `AOG`; on an airframe with a non-null `assigned_lease_id` it heads its own cascade, described in §3.7. A `RETURN_TO_SERVICE` event is accepted from `IN_MAINTENANCE` or `AOG`; it resets `hours_since_last_check` and `cycles_since_last_check` to 0, and lands the airframe in `ASSIGNED` when `assigned_lease_id` is non-null or `AVAILABLE` when it is null. A `RETIRE` event is accepted from `AVAILABLE`, `IN_MAINTENANCE` or `AOG` and only while `assigned_lease_id` is null; it sets `status` to the terminal `RETIRED` and removes the airframe from the substitution candidate pool permanently. An event whose `event_type` does not match the airframe's current posture — a `RETURN_TO_SERVICE` on an `AVAILABLE` airframe, a `RETIRE` on one still assigned — is rejected with `ERR_AIRCRAFT_UNAVAILABLE`.

Crew members are registered by operations control with a `full_name` as printed on the general declaration, an `employee_no` payroll number unique across the crew register, a `crew_role` of `CAPTAIN`, `FIRST_OFFICER` or `CABIN`, and a non-empty `type_ratings` array of the ICAO type designators the crew member currently holds a rating on. A new crew member starts `ACTIVE` — the alternatives being `GROUNDED` and `INACTIVE` — with `rolling_duty_minutes_7d` and `rolling_block_minutes_28d` both 0. Reading a crew member back recomputes both exposure figures against the current logical clock before returning them.

### 3.2. Structuring the ACMI Lease and Filing for Operational Control

A `LessorOpsController` drafts the lease by naming the counterparty and the airframe — `lessee_id` and `primary_aircraft_id` — and the calendar term as `term_start_date` and `term_end_date`, both `YYYY-MM-DD` UTC dates, both inclusive, with the end date not earlier than the start date. Commercially the lease carries `block_hour_rate_usd_cents`, the all-in ACMI rate per block hour in cents (at least 1); `min_guaranteed_block_hours_per_month`, a strictly positive number of hours carried to four decimal places representing the guarantee before proration; and `shortfall_credit_pct`, a fraction between 0 and 1 inclusive, carried to four decimal places, giving the share of lessor-attributable shortfall value credited back to the lessee.

The responsibility split is declared by four enumerated fields. `crew_provided_by`, `maintenance_provided_by` and `insurance_provided_by` each name the party furnishing flight and cabin crew, continuing-airworthiness management and line maintenance, and hull and liability cover respectively; each is `LESSOR` or `LESSEE`. `operational_control` declares who holds operational control and is likewise `LESSOR` or `LESSEE`. The structural rule is unconditional: whenever the lessor furnishes both crew and maintenance, `operational_control` must be `LESSOR`, because a lessor-crewed and lessor-maintained arrangement in which the lessee holds operational control is not a lawful wet lease. The mixture is refused with `ERR_OPERATIONAL_CONTROL_MISMATCH` (HTTP 422), both when the lease is drafted and again when it is filed with the authority.

Three further enumerated fields set the operating regime. `substitution_rights` is `LESSOR_UNILATERAL` or `LESSEE_CONSENT_REQUIRED`, deciding whether the lessor may swap airframes on its own authority. `reliability_basis` is `DEPARTURE` or `SCHEDULED`, deciding which reliability variant binds. `required_maintenance_program_ref` names the programme any airframe put on this lease must be enrolled in.

The redelivery bargain is fixed at drafting time too: `return_hours_since_check_max` and `return_cycles_since_check_max` cap how much life the airframe may have consumed since its last heavy check when handed back; `return_fuel_kg_required` sets the fuel on board expected at handover; `return_liability_cap_cents` caps the discrepancy charge before the minimum-fee floor is applied; `return_deposit_cents` is the maintenance reserve deposit the lessor holds against discrepancies; and `redelivery_icao` is the four-letter ICAO aerodrome code the airframe must be returned to. Each of the four cents-and-count ceilings is a non-negative figure.

A freshly drafted lease has `status` `DRAFT`, `suspension_reason` null, `lifetime_credited_block_minutes` 0, `return_deposit_applied_cents` 0 and `return_deposit_remaining_cents` equal to `return_deposit_cents`. Its `status` will travel through `DRAFT`, `PENDING_REGULATORY_APPROVAL`, `APPROVED`, `ACTIVE`, `SUSPENDED` and `TERMINATING` before settling in one of the two terminal states, `RETURNED` or `WITHDRAWN`.

**Filing.** Operations control files the arrangement with the authority by supplying the `authority_docket_no` the authority has opened for the application. Filing is admissible only from `DRAFT`, requires the operational-control structure to be lawful, and requires the lessee to be `ACTIVE`; it advances the lease from `DRAFT` to `PENDING_REGULATORY_APPROVAL`. When the lease owns no prior docket, a `RegulatoryApproval` row is created against it with `determination` `UNDER_REVIEW`, `review_round` 1, and both `conditions` and `open_condition_codes` empty. When the lease already owns a docket whose `determination` is `DENIED`, no second row is created: that docket is refiled in place, moving `DENIED` back to `UNDER_REVIEW`, incrementing `review_round` by 1, resetting `conditions` and `open_condition_codes` to empty, clearing `decided_at`, and overwriting `authority_docket_no` with the newly supplied value.

**Determination.** The authority records its ruling by supplying a `determination` of `APPROVED`, `CONDITIONAL` or `DENIED`, optionally with a `conditions` array of condition codes and an `expires_on` calendar date on which the ruling lapses. Every determination sets `decided_at` to the current logical instant. An `APPROVED` ruling requires the `conditions` payload to be absent or empty. A `CONDITIONAL` ruling requires a non-empty `conditions` array and copies it into `open_condition_codes`. Both `APPROVED` and `CONDITIONAL` advance the lease from `PENDING_REGULATORY_APPROVAL` to `APPROVED` — the same lease outcome, the difference being that a conditional lease carries open conditions to clear before its term ends. A `DENIED` ruling sends the lease from `PENDING_REGULATORY_APPROVAL` back to `DRAFT` so the arrangement can be restructured and refiled, which is the revision loop that drives the docket `UNDER_REVIEW → DENIED → UNDER_REVIEW` with `review_round` climbing on each pass. A determination requested from a docket that is not in a declared source state — anything other than `UNDER_REVIEW` for the first three rulings, or other than `CONDITIONAL` for the denial of a conditioned docket — is rejected with `ERR_APPROVAL_INVALID_STATE`.

Conditions are cleared by supplying a `cleared_condition_codes` array. The clearance is admissible only while the `determination` is `CONDITIONAL`, and only when every code still listed in `open_condition_codes` appears in the supplied array — that is, when nothing would remain open afterwards. The named codes are removed, `open_condition_codes` becomes empty, `decided_at` is refreshed to the current logical instant, and the docket is upgraded from `CONDITIONAL` to `APPROVED`. A `CONDITIONAL` docket may instead be denied, which sets `decided_at` and, when the lease has not yet been activated, returns the lease from `APPROVED` to `DRAFT`.

Revocation is the docket's terminal act. The authority revokes from `APPROVED` or from `CONDITIONAL` by supplying a `revocation_reason`; the docket moves to the terminal `REVOKED`, `decided_at` is set, the lease moves from `ACTIVE` to `SUSPENDED` with `suspension_reason` `REGULATORY_APPROVAL_REVOKED`, every leg on that lease still `SCHEDULED` or `DISPATCHED` is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `REGULATORY`, and each such cancellation recomputes the affected crew members' rolling exposure and the covering open month's charge. Because `REVOKED` is terminal, a lease suspended for this reason can never be reactivated.

**Withdrawal.** A lease that never entered service may be withdrawn by operations control with a `withdrawal_reason`, from `DRAFT`, from `PENDING_REGULATORY_APPROVAL` or from `APPROVED`, moving it to the terminal `WITHDRAWN`. Withdrawal sets every docket on the lease whose `determination` is `UNDER_REVIEW`, `CONDITIONAL` or `APPROVED` to `REVOKED`, sets every `CrewQualification` on the lease that is `QUALIFIED` to the terminal `REVOKED`, and releases any airframe assigned to the lease by clearing `assigned_lease_id` and moving its `status` from `ASSIGNED` to `AVAILABLE`.

### 3.3. Evidencing Insurance Cover

The underwriter attaches a certificate of insurance to a lease by supplying the `lease_id`, the broker's `certificate_no` (unique across all certificates), the agreed hull value as `hull_limit_usd_cents`, the combined single limit for third-party and passenger liability as `liability_limit_usd_cents`, two booleans — `breach_of_warranty_endorsed`, recording whether an AVN67B-style breach-of-warranty endorsement in favour of the lessee is attached, and `additional_insured_lessee`, recording whether the lessee is named additional insured — and the coverage window as `effective_from` and `expires_at` instants. The coverage interval is treated as **closed on both ends**: an instant exactly equal to `effective_from` or exactly equal to `expires_at` is covered.

Two floors apply at issue. `hull_limit_usd_cents` must be at least 5,000,000,000 cents — USD 50 million — and `liability_limit_usd_cents` at least 50,000,000,000 cents — USD 500 million; a certificate falling below either floor is refused with `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` (HTTP 422). Separately, a new certificate's closed interval must not overlap that of any existing `ACTIVE` certificate on the same lease. Overlap is judged with both comparisons inclusive — the new window's start not later than the existing window's end, and the existing window's start not later than the new window's end — so two intervals that merely touch at a single instant *do* conflict, and the rejection is `ERR_INSURANCE_PERIOD_OVERLAP` (HTTP 409). There is no tolerance buffer.

A new certificate is created with `status` `ACTIVE` and `revocation_reason` null. Its `status` may later become `EXPIRED`, `REVOKED` or `SUPERSEDED`, all three terminal. When the lease is `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSED` and a prior certificate on that lease is still `ACTIVE` while its window does not overlap the new one, that prior certificate moves from `ACTIVE` to `SUPERSEDED`: the lease's state is unchanged by the supersession itself, and the superseded certificate stops counting toward dispatch cover.

Attaching a conforming replacement certificate is also what lifts an insurance-driven suspension. When the lease is `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSED` and the new certificate has `additional_insured_lessee` true and a closed coverage interval containing the current logical instant, the lease returns from `SUSPENDED` to `ACTIVE` and `suspension_reason` is set back to null. Legs already cancelled by the lapse are not restored.

Revocation runs the other way. The underwriter pulls cover by supplying a `revocation_reason` on an `ACTIVE` certificate, which moves it to `REVOKED` and records the reason. If no `ACTIVE` certificate remains on the lease afterwards, the four-level lapse cascade of §2.7 runs in full: the lease drops from `ACTIVE` to `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSED`, every leg still `SCHEDULED` or `DISPATCHED` on that lease is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `INSURANCE_LAPSE`, and each cancellation recomputes that leg's crew exposure and the open month's charge. The same second-level and lower cascade fires when the logical clock is advanced past an `ACTIVE` certificate's `expires_at`, which moves the certificate to `EXPIRED`.

### 3.4. Crew Qualification and Duty-Limit Management

Flying under someone else's operating certificate requires more than a type rating: the crew must be trained on the lessee's procedures. Operations control enrols a crew member for a specific lease by supplying `crew_member_id` and `lease_id`, creating a `CrewQualification` in `status` `TRAINING` — the other states being `QUALIFIED`, `EXPIRED` and the terminal `REVOKED`. The pairing is many-to-many: one crew member may hold qualifications on several leases, and one lease qualifies many crew members.

The checkride converts training into authority. Operations control records it by supplying `differences_training_completed_on`, the `YYYY-MM-DD` date the lessee-procedures differences course was completed, and `checkride_valid_until`, the `YYYY-MM-DD` date the line check expires. The record is admissible from `TRAINING` or from `EXPIRED`, and the crew member must be `ACTIVE`. Both dates are stored. If `checkride_valid_until` is strictly later than the current logical date the qualification becomes `QUALIFIED`; otherwise the record is stored and the qualification is set to `EXPIRED` instead. When the logical clock is later advanced past a `QUALIFIED` record's `checkride_valid_until`, the qualification lapses from `QUALIFIED` to `EXPIRED` and legs that would use that crew member on that lease are refused with `ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES`. Recording a fresh checkride on an `EXPIRED` record returns it to `QUALIFIED`, which is the recurrent-line-check cycle `QUALIFIED → EXPIRED → QUALIFIED`. When a lease reaches `RETURNED` or `WITHDRAWN`, every qualification on it — whether `TRAINING`, `QUALIFIED` or `EXPIRED` — is set to `REVOKED`, and lessee-procedures authority for that lease ends permanently.

**Duty and block exposure.** Two rolling exposures are tracked per crew member, both anchored on the logical clock and both **half-open** at the recent end: the window includes its start instant and excludes the clock instant itself. `rolling_duty_minutes_7d` is the sum, over the crew member's legs whose `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED` and whose `scheduled_out` falls within the last seven days — that is, at or after the instant 168 hours before the clock and strictly before the clock — of each leg's scheduled block minutes plus a fixed pre- and post-flight duty allowance of 105 minutes. `rolling_block_minutes_28d` is the sum of the scheduled block minutes alone, over the same status filter, for legs whose `scheduled_out` falls within the last twenty-eight days — at or after the instant 672 hours before the clock and strictly before it. A crew member counts a leg whether they are its `captain_id` or its `first_officer_id`. Cancelled and diverted legs are excluded from both sums, which is exactly what makes a cancellation an exact compensation for the scheduling that preceded it. Window boundaries are compared to the millisecond, and both sums are whole minutes.

Admission of a new or dispatching leg is decided not on the stored figures but on a **projection anchored on the candidate leg's own scheduled off-blocks instant**. For the crew member under test, the projected seven-day duty is that crew member's candidate leg duty — its scheduled block minutes plus the 105-minute allowance — plus the same duty figure summed over that crew member's other legs in `SCHEDULED`, `DISPATCHED` or `COMPLETED` whose `scheduled_out` falls at or after the instant 168 hours before the candidate's off-blocks instant and strictly before that instant. The projected twenty-eight-day block exposure is the candidate leg's scheduled block minutes plus the scheduled block minutes of that same restricted set of legs whose `scheduled_out` falls at or after 672 hours before the candidate's off-blocks instant and strictly before it.

The limits are 3,600 minutes of projected seven-day duty — sixty hours — and 5,400 minutes of projected twenty-eight-day block time — ninety hours. The boundary is inclusive on the admissible side: a projection landing exactly on 3,600 or exactly on 5,400 minutes is admitted, and only a strictly greater projection is refused. Exceeding the duty limit yields `ERR_CREW_DUTY_LIMIT_EXCEEDED` (HTTP 409); exceeding the block limit yields `ERR_CREW_BLOCK_LIMIT_EXCEEDED` (HTTP 409). The captain is tested first and the first officer second, so when both would breach, the captain's failure is the one reported.

### 3.5. Bringing the Lease Into Force, Suspension and Reactivation

Activation is the densest gate in the system. Operations control brings an `APPROVED` lease into force only when all of the following hold. The lease must own a `RegulatoryApproval` whose `determination` is `APPROVED` or `CONDITIONAL` and whose `expires_on` is either null or not earlier than the current logical date; otherwise `ERR_REGULATORY_APPROVAL_MISSING` (HTTP 409). The lease must carry at least one `InsuranceCertificate` with `status` `ACTIVE`, `additional_insured_lessee` true, `breach_of_warranty_endorsed` true, `hull_limit_usd_cents` at or above the USD 50 million floor, `liability_limit_usd_cents` at or above the USD 500 million floor, and a closed coverage interval containing midnight UTC at the start of `term_start_date`; otherwise `ERR_INSURANCE_COVERAGE_MISSING` (HTTP 409). The airframe named by `primary_aircraft_id` must have a `maintenance_program_ref` equal to the lease's `required_maintenance_program_ref`; otherwise `ERR_MAINTENANCE_PROGRAM_MISALIGNED` (HTTP 422). The lessee must be `ACTIVE`. And at least one `CrewQualification` on the lease must be `QUALIFIED` for a crew member whose `crew_role` is `CAPTAIN` — a lease cannot come into force without a qualified commander.

The airframe check has two admissible shapes. On a first activation the airframe must be `AVAILABLE` with `assigned_lease_id` null. On the reactivation of a suspended lease the airframe is already `ASSIGNED` with `assigned_lease_id` equal to this lease, because it never left the lease. Anything else is refused with `ERR_AIRCRAFT_UNAVAILABLE` (HTTP 409).

A first activation moves the lease from `APPROVED` to `ACTIVE` and does three things besides. It sets the primary airframe from `AVAILABLE` to `ASSIGNED` and writes `assigned_lease_id` to the lease. It initialises the deposit split, setting `return_deposit_remaining_cents` to `return_deposit_cents` and `return_deposit_applied_cents` to 0. And it opens the first monthly settlement window: a `UtilizationPeriod` for this lease with `status` `OPEN` and `period_month` equal to the `YYYY-MM` month of whichever is later, `term_start_date` or the current logical date, with its prorated minimum guarantee computed as described in §3.8 — but only when no period already exists for that lease and month.

**Suspension.** An `ACTIVE` lease is driven to `SUSPENDED` by exactly three system events, each stamping its own `suspension_reason`: the last `ACTIVE` certificate on the lease leaving `ACTIVE` sets `INSURANCE_LAPSED`; revocation of the authority docket sets `REGULATORY_APPROVAL_REVOKED`; and the assigned airframe being grounded AOG sets `AIRFRAME_AOG`. In every case the legs still `SCHEDULED` or `DISPATCHED` on the lease are cancelled into `CANCELLED_LESSOR` with `cancelling_party` `LESSOR` and a `cancel_reason` matched to the cause — `INSURANCE_LAPSE`, `REGULATORY` or `TECHNICAL` respectively — and each cancellation recomputes crew exposure and the open month's charge. `suspension_reason` is null in every state other than `SUSPENDED`.

**Reactivation** depends on which cause suspended the lease, and the three paths differ. An `INSURANCE_LAPSED` suspension lifts automatically when a conforming replacement certificate is attached, as described in §3.3; the lease returns from `SUSPENDED` to `ACTIVE` and `suspension_reason` is cleared to null without any further operator action. An `AIRFRAME_AOG` suspension does not lift automatically: after technical control has returned the airframe to service, so that it is `ASSIGNED` with `assigned_lease_id` equal to this lease, operations control must explicitly activate the lease again, which is admissible only while `suspension_reason` is `AIRFRAME_AOG` and at least one `ACTIVE` certificate on the lease covers the current logical instant. That reactivation clears `suspension_reason` to null, creates no further utilization period, and restores no cancelled leg. A `REGULATORY_APPROVAL_REVOKED` suspension is unrecoverable, because the docket's `REVOKED` determination is terminal.

Any lease transition requested from a status that is not a declared source of that transition is refused with `ERR_LEASE_INVALID_STATE` (HTTP 409). That guard covers submission for approval, activation, termination, and — because these operations are only meaningful against a live arrangement — attaching a certificate, requesting a substitution, scheduling a leg and filing a reliability report.

### 3.6. Flying the Programme: Scheduling Through Close-Out

Operations control schedules a leg under a live lease by supplying `lease_id`, `aircraft_id`, `captain_id`, `first_officer_id`, the four-letter `origin_icao` and `dest_icao` aerodrome codes, a `leg_class` of `REVENUE`, `REPOSITIONING` or `MAINTENANCE_FERRY`, and the scheduled off- and on-blocks instants `scheduled_out` and `scheduled_in`, the latter strictly after the former. When `aircraft_id` is omitted it defaults to the lease's `primary_aircraft_id`. The leg is created with `status` `SCHEDULED` and `billing_state` `UNBILLED`; `actual_out`, `actual_in`, `cancelling_party` and `cancel_reason` are all null, `technical_delay_minutes` is 0, `block_minutes` and `billable_block_minutes` are 0, and `crew_requalification_required` is false.

`scheduled_block_minutes` is computed once at creation and never changes: it is the whole number of minutes between `scheduled_out` and `scheduled_in`, with any remaining seconds discarded.

Scheduling runs the full admission ladder. The leg must fall inside the lease term — the calendar date of `scheduled_out` not earlier than `term_start_date` and the calendar date of `scheduled_in` not later than `term_end_date` — else `ERR_LEG_OUTSIDE_LEASE_TERM` (HTTP 422). Both pilots must hold the operating airframe's exact `type_designator` in their `type_ratings` array and must themselves be `ACTIVE`, else `ERR_CREW_NOT_TYPE_RATED` (HTTP 422). Both projected exposures must stay within limits per §3.4. Both pilots must hold a `QUALIFIED` qualification for this lease, else `ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES` (HTTP 409). And the airframe must be free.

**Airframe occupancy.** An existing leg on the same airframe, in `SCHEDULED`, `DISPATCHED` or `COMPLETED`, occupies its airframe from forty-five minutes before its `scheduled_out` until forty-five minutes after its `scheduled_in`, and that occupancy window is half-open — the start instant belongs to it, the end instant does not. The candidate leg's own half-open interval runs from its `scheduled_out` up to but not including its `scheduled_in`. The two conflict when the candidate's off-blocks instant is strictly earlier than the occupancy window's end *and* the occupancy window's start is strictly earlier than the candidate's on-blocks instant. Consequently a candidate that begins exactly at an occupancy window's end does **not** conflict. A conflict is refused with `ERR_AIRCRAFT_SCHEDULE_CONFLICT` (HTTP 409).

**Dispatch.** Releasing a leg for departure is admissible only from `SCHEDULED`, advances `status` from `SCHEDULED` to `DISPATCHED`, and records the supplied `actual_out` off-blocks instant. It re-runs the gates at the dispatch instant rather than trusting the ones passed at scheduling: the lease must be `ACTIVE`; the airframe named by the leg must be `ASSIGNED`, else `ERR_AIRCRAFT_UNAVAILABLE`; a certificate on the lease must be `ACTIVE` with `additional_insured_lessee` true and a closed coverage interval containing `actual_out`, else `ERR_INSURANCE_COVERAGE_MISSING`; both pilots' qualifications for the lease must be `QUALIFIED`; both must hold the airframe's `type_designator`; and both projected exposures must remain within limits. `billing_state` is left exactly as it was.

**Completion.** Closing out a leg is admissible only from `DISPATCHED` and requires the supplied `actual_in` on-blocks instant to be strictly later than the recorded `actual_out`. It advances `status` from `DISPATCHED` to `COMPLETED`, stores `actual_in` and the optionally supplied `technical_delay_minutes` (a non-negative count of departure-delay minutes attributable to a technical defect, defaulting to 0), and writes `block_minutes` as the whole number of minutes between `actual_out` and `actual_in` with the remaining seconds discarded.

`billable_block_minutes` is then set by leg class. A `MAINTENANCE_FERRY` leg is never billable and takes 0. A `REPOSITIONING` leg takes its `block_minutes` exactly, with no floor applied. A `REVENUE` leg is subject to a minimum billable block of one hour: if `block_minutes` is at least 60 the billable figure is `block_minutes` itself, and otherwise it is 60. Because the comparison is inclusive, a 60-minute revenue leg bills 60 minutes and a 59-minute revenue leg also bills 60.

Completion also advances the airframe's counters: `block_minutes` divided by 60 is added to both `airframe_hours_total` and `hours_since_last_check`, each rounded to two decimal places, and `cycles_since_last_check` is increased by 1. Finally, the lease's `OPEN` utilization period for the month of the leg's `scheduled_out` is recomputed under the `PROVISIONAL` variant, and the exposures of both pilots are recomputed.

**Cancellation and diversion.** Cancelling a leg requires a `cancelling_party` of `LESSEE` or `LESSOR` and a `cancel_reason` of `TECHNICAL`, `COMMERCIAL`, `WEATHER`, `CREW`, `INSURANCE_LAPSE` or `REGULATORY`. It is admissible from `SCHEDULED` or from `DISPATCHED`; from any other status the rejection is `ERR_LEG_INVALID_STATE` (HTTP 409). A `SCHEDULED` leg cancelled by the lessee moves to `CANCELLED_LESSEE`; cancelled by the lessor it moves to `CANCELLED_LESSOR`. Either way `cancelling_party` and `cancel_reason` are recorded, `billing_state` is set to `CREDITED`, the rolling exposures of both `captain_id` and `first_officer_id` are recomputed — releasing the cancelled leg's duty and block contribution — and the lease's `OPEN` period is recomputed under the `PROVISIONAL` variant. A lessor cancellation additionally raises the month's lessor-attributable shortfall. A leg already `DISPATCHED` and cancelled with `cancel_reason` `WEATHER` is treated as a diversion instead: `status` becomes `DIVERTED`, `billing_state` becomes `CREDITED`, and `billable_block_minutes` stays 0 because no on-blocks instant was ever recorded. Diverted legs, like cancelled ones, contribute nothing to either charge variant.

**The financial dimension.** A leg's `billing_state` advances on billing events only. Preparing a `PROVISIONAL` invoice over the leg's period moves every leg of that period from `UNBILLED` to `PROVISIONALLY_BILLED`, provided the leg's `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED`, and leaves `status` untouched. When the period settles, every `COMPLETED` leg of the month whose `billing_state` is `UNBILLED` or `PROVISIONALLY_BILLED` moves to `FINALIZED`, freezing that leg's minutes against further period recomputation — a leg previously provisionally billed and a leg never invoiced both land in `FINALIZED` by this route.

### 3.7. Airframe Substitution and Irregular Operations Recovery

When an airframe goes AOG, enters a scheduled check, or an irregular operation demands a different tail, the lessor substitutes. Operations control requests the swap by supplying `lease_id`, `original_aircraft_id`, a `reason` of `AOG`, `SCHEDULED_MAINTENANCE` or `IRREGULAR_OPS`, the `effective_from` instant from which the substitute takes over, and the `expected_lease_version` required by §2.6. Optionally the request names `substitute_aircraft_id` directly and may carry a `consent_note`. The lease must be in a status from which a substitution is declared, and the substitute must be enrolled in the lease's `required_maintenance_program_ref`, else `ERR_MAINTENANCE_PROGRAM_MISALIGNED`.

**Client-specified substitute.** When `substitute_aircraft_id` is supplied, `selection_basis` is recorded as `CLIENT_SPECIFIED` and the named airframe must satisfy every eligibility test: its `type_family` must equal the original's `type_family` (the exact `type_designator` may differ, which is what makes the crew-rating cascade reachable), its `seat_count` must be at least the original's `seat_count` less a tolerance of five seats, its `status` must be `AVAILABLE`, its `assigned_lease_id` must be null, and its `hours_since_last_check` must not exceed 400.00 hours. A failure on any of these is refused with `ERR_SUBSTITUTION_TYPE_MISMATCH` (HTTP 422).

**Server-selected substitute.** When `substitute_aircraft_id` is omitted, the server picks one and records `selection_basis` as `SERVER_SELECTED`. The eligible pool is every airframe other than the original whose `status` is `AVAILABLE`, whose `assigned_lease_id` is null, whose `type_family` equals the original's `type_family`, whose `maintenance_program_ref` equals the lease's `required_maintenance_program_ref`, whose `seat_count` is at least the original's `seat_count` less five, and whose `hours_since_last_check` is not more than 400.00 hours — the boundary being inclusive, so an airframe at exactly 400.00 hours remains eligible. `RETIRED`, `IN_MAINTENANCE`, `AOG` and already-assigned airframes are therefore all excluded. Because eligibility turns on the family rather than the variant, a different-variant airframe of the same family is a lawful substitute even when the rostered crew are not rated on that variant.

The pool is then ranked by three keys, each ascending and applied in order: first the absolute difference between the candidate's `seat_count` and the original's `seat_count`, so the closest-gauge airframe wins; then the candidate's `hours_since_last_check`, so the freshest airframe wins a seat tie; and finally the candidate's `created_at`, so the longest-registered airframe wins any remaining tie. The row identifier is never used as a tie-break. The first-ranked candidate becomes the substitute. If the pool is empty the request is refused with `ERR_NO_SUBSTITUTE_AIRCRAFT_AVAILABLE` (HTTP 409).

Either way the request records `seat_delta` as the substitute's `seat_count` less the original's `seat_count` — a figure the lessee needs for its consent decision — and `repointed_leg_count` as 0 at creation, and the lease's `version` increments by 1.

**The consent fork.** A substitution begins conceptually in `REQUESTED` and immediately forks on the lease's `substitution_rights`, and the two branches carry deliberately different side effects. On a lease whose rights are `LESSEE_CONSENT_REQUIRED` the request lands in `LESSEE_CONSENT_PENDING`, `seat_delta` is written, no airframe is touched yet, and no prior request on the lease is disturbed. On a lease whose rights are `LESSOR_UNILATERAL` the request lands directly in `APPROVED`, `seat_delta` is written, no airframe is touched yet, and — this is the branch's extra effect — every other substitution on the same lease whose `status` is `REQUESTED`, `LESSEE_CONSENT_PENDING` or `APPROVED` is moved to the terminal `WITHDRAWN`, without touching any airframe.

A `Lessee` rules on a pending request by supplying a `decision` of `GRANT` or `WITHHOLD`, optionally with a `consent_note`, and only when its `X-User-ID` matches the lease's `lessee_id`. `GRANT` moves the request from `LESSEE_CONSENT_PENDING` to `APPROVED`; `WITHHOLD` moves it to the terminal `REJECTED` and the original airframe stays on the lease. Both record the note.

**Effectuation.** Operations control effectuates an `APPROVED` substitution. The substitute must be `AVAILABLE` with `assigned_lease_id` null, must be enrolled in the lease's required maintenance programme, and the lease must be `ACTIVE` or `SUSPENDED`. An effectuation attempted while the request is still awaiting lessee consent on a consent-required lease is refused with `ERR_SUBSTITUTION_CONSENT_REQUIRED` (HTTP 403) — a lessor operator may never move a pending request to `APPROVED` by this route.

Effectuation moves the request to the terminal `EFFECTIVE` and runs the four-level cascade. Level one: the substitute's `status` becomes `ASSIGNED` and its `assigned_lease_id` the lease; the original airframe has `assigned_lease_id` cleared and its `status` moved from `ASSIGNED` to `AVAILABLE`, except that an original already `IN_MAINTENANCE` or `AOG` keeps that status; and the lease's `primary_aircraft_id` is re-pointed to the substitute. Level two, caused by that re-point: every leg on the lease whose `status` is `SCHEDULED`, whose `aircraft_id` is the original airframe, and whose `scheduled_out` is at or after the substitution's `effective_from`, has its `aircraft_id` re-pointed to the substitute, and `repointed_leg_count` is written with the number re-pointed. Level three, caused by each leg re-point: any re-pointed leg whose captain or first officer does not hold the substitute's `type_designator` in `type_ratings` has `crew_requalification_required` set to true and is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `CREW`. Level four, caused by each such cancellation: the `rolling_duty_minutes_7d` and `rolling_block_minutes_28d` of that leg's captain and first officer are recomputed, and the lease's `OPEN` utilization period covering the leg's `scheduled_out` is recomputed under the `PROVISIONAL` variant. The lease's `version` increments by 1.

The AOG path into all of this runs through technical control. A `GROUND_AOG` maintenance event on an airframe with a non-null `assigned_lease_id` cancels every leg on that airframe still `SCHEDULED` or `DISPATCHED` into `CANCELLED_LESSOR` with `cancelling_party` `LESSOR` and `cancel_reason` `TECHNICAL`, drives the owning lease from `ACTIVE` to `SUSPENDED` with `suspension_reason` `AIRFRAME_AOG`, and recomputes crew exposure and the covering open month's charge for each cancelled leg. Returning that airframe to service resets its check counters but does **not** itself un-suspend the lease; the explicit reactivation described in §3.5 is still required.

### 3.8. Monthly Utilization: Guarantee, Shortfall, Overrun and Reliability

A `UtilizationPeriod` is the monthly settlement window for one lease. Its `period_month` is a server-assigned `YYYY-MM` string, unique per lease, and its `status` travels `OPEN`, `PENDING_SETTLEMENT`, `SETTLED`, `DISPUTED` and `REOPENED`. The first window is opened by lease activation; each close opens the next.

**Step one: prorating the guarantee.** `mgh_effective_hours` is the lease's `min_guaranteed_block_hours_per_month` multiplied by the number of covered days and divided by the number of calendar days in `period_month`, rounded half up to four decimal places. A day of `period_month` is covered when it falls on or after `term_start_date` and on or before `term_end_date`, both bounds inclusive. A lease that runs the whole month therefore carries its full guarantee; one that starts mid-month carries a fraction of it.

**Step two: which legs count, and for how many minutes.** This is where the two variants diverge, and identical leg data yields different answers.

Under the `PROVISIONAL` variant the include-set is every leg of the lease whose `scheduled_out` falls inside `period_month` and whose `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED`. A `COMPLETED` leg contributes its `billable_block_minutes`. A leg not yet completed contributes its `scheduled_block_minutes`, with the same one-hour minimum billable floor applied when its `leg_class` is `REVENUE` and with 0 contributed when its `leg_class` is `MAINTENANCE_FERRY`. Cancelled and diverted legs contribute nothing at all, so no lessee-cancellation credit ever appears in a provisional figure.

Under the `FINAL` variant the include-set is narrower in one respect and wider in another. Only legs whose `status` is `COMPLETED` count from the operational side, each contributing its `billable_block_minutes`. To that is added, for every leg whose `status` is `CANCELLED_LESSEE`, a contribution of half its `scheduled_block_minutes` — the lessee pays for half of what it cancelled. Legs in `CANCELLED_LESSOR` and `DIVERTED` contribute nothing. Legs in `SCHEDULED` or `DISPATCHED` cannot exist when the final variant runs, because clearing them is a precondition of closing the month.

**Step three: the pinned rounding order.** Each included leg's minute contribution is divided by 60 and rounded half up to four decimal places *first*; `credited_hours` is the sum of those rounded per-leg figures. `credited_block_minutes` is separately the plain sum of the same per-leg minute contributions, in whole minutes. Legs are enumerated by `scheduled_out` ascending with `created_at` ascending as tie-break, though because the contributions are simply summed the order does not change the result.

**Step four: shortfall or overrun, decided strictly.** When `credited_hours` is strictly less than `mgh_effective_hours`, `shortfall_hours` is their difference rounded half up to four decimal places and `overrun_hours` is 0. Otherwise `shortfall_hours` is 0 and `overrun_hours` is `credited_hours` less `mgh_effective_hours`, rounded half up to four decimal places — so a month landing exactly on the guarantee produces neither. Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure. The lessee is credited only for shortfall the lessor actually caused.

**Step five: the cents components, each rounded before summation.** `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents. `shortfall_credit_cents` is `lessor_attributable_shortfall_hours` multiplied by that same rate and by the lease's `shortfall_credit_pct`, rounded half up to whole cents.

The overrun is charged in three tiers whose widths are fractions of the prorated guarantee. The first tier is 10 percent of `mgh_effective_hours`, rounded half up to four decimal places; the second tier is 15 percent of `mgh_effective_hours`, likewise rounded to four decimal places. The first tier's hours are the lesser of `overrun_hours` and the first tier width. The second tier's hours are the lesser of the second tier width and whatever remains of `overrun_hours` after the first tier width is removed, floored at zero. The third tier's hours are whatever remains of `overrun_hours` after both tier widths are removed, floored at zero. Each tier's hours are multiplied by the block-hour rate and by that tier's multiplier — 1.00 for the first tier, 1.15 for the second, and 1.35 for the third — and each of the three products is rounded half up to whole cents *individually*; `overrun_charge_cents` is the sum of those three rounded figures.

`gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.

**Step six: the reliability penalty and the net charge.** `reliability_penalty_cents` is derived as described below, and the net charge is `gross_charge_cents` less `reliability_penalty_cents`. Under the `PROVISIONAL` variant that net figure is written to `provisional_charge_cents`; under the `FINAL` variant it is written to `final_charge_cents`. `variant_applied` records which variant last wrote the credited, shortfall and overrun fields.

**The reliability penalty itself.** The penalty consumes the single `ReliabilityReport` for this lease and `period_month` whose `status` is `ACCEPTED`; when more than one such report exists, the one with the greatest `created_at` is used, and reports still `SUBMITTED` or already `REJECTED` are ignored entirely. If no accepted report exists for the month, `reliability_penalty_cents` is 0 and no penalty applies.

Otherwise the accepted report's `technical_dispatch_reliability_pct` is compared against a contractual guarantee of 99.00 percent. The deficit factor is the amount by which the reliability figure falls short of 99.00, divided by 5.0, floored at zero and capped at 10.0, rounded half up to four decimal places — so every five percentage points of shortfall contributes one whole unit of deficit factor, and a report at or above 99.00 percent yields a factor of zero. The penalty rate is then chosen by tier on the **gross** charge, evaluated with strict comparisons: a `gross_charge_cents` below 5,000,000 cents (USD 50,000) attracts 2 percent, a gross charge below 25,000,000 cents (USD 250,000) attracts 3.5 percent, and anything at or above that attracts 5 percent. `reliability_penalty_cents` is `gross_charge_cents` multiplied by that rate and by the deficit factor, rounded half up to whole cents.

The evaluation order here is contractual: the tier is keyed on `gross_charge_cents` as computed in step five, *before* any penalty is subtracted. The tier is never re-derived from the net figure and no fixed-point iteration is performed, even where subtracting the penalty would have pushed the net charge into a lower tier.

**When each variant runs.** The provisional variant is recomputed on every leg creation, dispatch, completion and cancellation that touches an `OPEN` period, and is what a `PROVISIONAL` invoice draws on. The final variant runs when a period moves from `OPEN` to `PENDING_SETTLEMENT` and again when it moves from `REOPENED` to `PENDING_SETTLEMENT`, and is what a `FINAL` invoice draws on.

**The settlement preview.** A non-mutating computed read evaluates both variants side by side without persisting anything. It returns `period_id`, `period_month`, `mgh_effective_hours`, `provisional_credited_hours`, `provisional_gross_charge_cents`, `final_credited_hours`, `final_shortfall_hours`, `final_overrun_hours`, `final_gross_charge_cents`, `reliability_penalty_cents` and `projected_final_charge_cents`. This is the instrument the desk and the lessee use to see, before a month is closed, exactly how much the variant switch will move the number.

**Closing the month.** A `BillingAdmin` closes an `OPEN` period, which is admissible only when no leg of the lease whose `scheduled_out` falls inside `period_month` is still `SCHEDULED` or `DISPATCHED`; otherwise the rejection is `ERR_PERIOD_INVALID_STATE` (HTTP 409), which is also the rejection for any period transition requested from an undeclared source status. Closing recomputes every charge field under the `FINAL` variant, sets `variant_applied` to `FINAL`, writes `final_charge_cents`, and increments the period's `version`. It also opens the following month's period with `status` `OPEN`, but only when that next month still falls inside the lease term and the lease's `status` is `ACTIVE` or `SUSPENDED`.

**Reliability reporting.** Technical control files the monthly report by supplying `lease_id`, `aircraft_id` and `period_month`; the report is created with `status` `SUBMITTED` and its `period_month` is unique per lease-and-airframe pair among reports that are not `REJECTED`. All four counts are derived from the `REVENUE` legs of that lease and airframe whose `scheduled_out` month equals `period_month`. `revenue_departures` counts those whose `status` is `DISPATCHED` or `COMPLETED`. `scheduled_revenue_legs` counts those whose `status` is `SCHEDULED`, `DISPATCHED`, `COMPLETED` or `CANCELLED_LESSOR`. `technical_delay_events` counts those whose `technical_delay_minutes` is strictly greater than 15. `technical_cancellations` counts those whose `status` is `CANCELLED_LESSOR` and whose `cancel_reason` is `TECHNICAL`.

Both reliability variants are then computed to two decimal places, round half up. `tdr_departure_basis_pct` is 100 multiplied by `revenue_departures` less `technical_delay_events`, divided by `revenue_departures`; when `revenue_departures` is 0 the figure is 100.00. This basis counts only airframes that actually went off-blocks, so lessor technical cancellations do not depress it. `tdr_scheduled_basis_pct` is 100 multiplied by `scheduled_revenue_legs` less `technical_delay_events` less `technical_cancellations`, divided by `scheduled_revenue_legs`; when `scheduled_revenue_legs` is 0 the figure is 100.00. This basis measures the whole published programme, so technical cancellations count against the operator twice over — once in the numerator subtraction and once by remaining in the denominator — and on identical leg data it yields a strictly lower percentage than the departure basis whenever `technical_cancellations` is greater than zero. Legs in `CANCELLED_LESSEE` and `DIVERTED` are excluded from both denominators, as are `SCHEDULED` legs from the departure basis. `technical_dispatch_reliability_pct` is then set to `tdr_departure_basis_pct` when the lease's `reliability_basis` is `DEPARTURE`, and to `tdr_scheduled_basis_pct` when it is `SCHEDULED`.

The lessee rules on the filed report by supplying a `decision` of `ACCEPT` or `REJECT`, optionally with a `review_note`, and only when its `X-User-ID` matches the lease's `lessee_id`. Acceptance moves the report from `SUBMITTED` to the terminal `ACCEPTED`, which both unblocks invoice approval for the same lease and month and feeds `technical_dispatch_reliability_pct` into the penalty on the next close. Rejection moves it from `SUBMITTED` to the terminal `REJECTED`, records the note, and frees the lease-airframe-month combination so a fresh report may be filed.

### 3.9. Settlement Invoicing, Segregation of Duties and Disputes

A `BillingAdmin` prepares the settlement invoice for a closed month by supplying `period_id`, the `expected_period_version` of §2.6, the `due_on` payment date, and optionally a `variant` of `PROVISIONAL` or `FINAL`; when `variant` is omitted it defaults to `FINAL`. The target period must be `PENDING_SETTLEMENT`, else `ERR_PERIOD_NOT_READY_FOR_SETTLEMENT` (HTTP 409).

The invoice is created with `status` `PREPARED`, its `lease_id` denormalised from the period for lessee-scoped queries, and `prepared_by_user_id` set to the acting `X-User-ID` while `approved_by_user_id` is null. `amount_cents` is frozen at preparation time: the period's `provisional_charge_cents` when `variant` is `PROVISIONAL`, and its `final_charge_cents` otherwise. `line_items` is an ordered array of rows, each carrying a `code`, an `hours` figure and a `cents` figure, for `BASE_GUARANTEE`, `SHORTFALL_CREDIT`, `OVERRUN_TIER1`, `OVERRUN_TIER2`, `OVERRUN_TIER3` and `RELIABILITY_PENALTY` in that order; a component valued at 0 cents is still emitted rather than suppressed. `void_reason` is null. Preparing an invoice with `variant` `PROVISIONAL` moves every leg of the period whose `billing_state` is `UNBILLED` to `PROVISIONALLY_BILLED`. Preparation increments the period's `version` by 1 — which is precisely why a second preparer working from a stale read is rejected.

**Approval.** Approval is admissible only from `PREPARED` and carries two gates. An `ACCEPTED` reliability report must exist for the invoice's lease and the period's `period_month`, else `ERR_RELIABILITY_REPORT_NOT_ACCEPTED` (HTTP 409). And the approving `X-User-ID` must differ from the invoice's `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval moves the invoice from `PREPARED` to `APPROVED` and writes `approved_by_user_id` with the approver's identifier.

**Issue.** Issue is admissible only from `APPROVED` and requires that the lessee's `outstanding_balance_usd_cents` plus the invoice's `amount_cents` not exceed the lessee's `credit_limit_usd_cents`; a breach is refused with `ERR_LESSEE_CREDIT_LIMIT_EXCEEDED` (HTTP 402). The same ceiling is tested at preparation time against the amount about to be invoiced. Issue moves the invoice from `APPROVED` to `ISSUED`, records `due_on`, adds `amount_cents` to the lessee's `outstanding_balance_usd_cents`, and — when the invoice's `variant` is `FINAL` — drives the period from `PENDING_SETTLEMENT` to `SETTLED`. That settlement moves every `COMPLETED` leg of the month from `UNBILLED` or `PROVISIONALLY_BILLED` to `FINALIZED`, adds the period's `credited_block_minutes` to the lease's `lifetime_credited_block_minutes`, and increments the period's `version`.

**Void.** Voiding is admissible from `PREPARED`, from `APPROVED` or from `ISSUED`, always records the supplied `void_reason`, and always lands in the terminal `VOID`. Voiding a `PREPARED` or `APPROVED` invoice leaves the lessee receivable untouched. Voiding an `ISSUED` invoice subtracts its `amount_cents` from the lessee's `outstanding_balance_usd_cents`, restoring the pre-issue figure exactly, and — when the invoice's `variant` is `FINAL` — drives the period from `SETTLED` back to `PENDING_SETTLEMENT` so a corrected invoice can be prepared. That reversion returns every leg of the month from `FINALIZED` to `PROVISIONALLY_BILLED` if it had been provisionally invoiced and to `UNBILLED` if it had not, subtracts the period's `credited_block_minutes` from the lease's `lifetime_credited_block_minutes`, and increments the period's `version`. An invoice transition requested from an undeclared source status is refused with `ERR_INVOICE_INVALID_STATE` (HTTP 409).

**Disputes.** A `Lessee` whose `X-User-ID` matches the lease's `lessee_id` may dispute a `SETTLED` month by supplying a `dispute_reason` and a `disputed_amount_cents`. The contested amount must be strictly greater than 0 and no greater than the period's `final_charge_cents`; anything outside that half-open range is refused with `ERR_INVALID_REQUEST` (HTTP 400). The dispute moves the period from `SETTLED` to `DISPUTED`, records both fields, and increments the period's `version`.

The settlement desk resolves the dispute by supplying a `resolution` of `REOPEN` or `UPHOLD_SETTLEMENT`, admissible only from `DISPUTED`. `UPHOLD_SETTLEMENT` returns the period from `DISPUTED` to `SETTLED`, clears `disputed_amount_cents` to 0, and keeps `dispute_reason` on the row for audit. `REOPEN` moves the period from `DISPUTED` to `REOPENED` and voids every invoice on the period whose `status` is `ISSUED`, each void decrementing the lessee's `outstanding_balance_usd_cents` by that invoice's `amount_cents`. `REOPENED` is a resting state: a subsequent close recomputes every charge field under the `FINAL` variant, rewrites `final_charge_cents`, returns the period to `PENDING_SETTLEMENT`, and — unlike a first close — creates no following month's period. That closes the cycle `SETTLED → DISPUTED → REOPENED → PENDING_SETTLEMENT → SETTLED`. Every one of these resolution and close steps increments the period's `version`.

### 3.10. Termination, Redelivery and Repositioning

Operations control serves termination on a lease that is `ACTIVE` or `SUSPENDED` by supplying a `termination_reason` of `EXPIRY`, `NOTICE` or `DEFAULT`. Termination is refused while any leg on the lease is still `DISPATCHED` — an aircraft in the air cannot be handed back. It moves the lease to `TERMINATING` and does three things. Every leg on the lease still `SCHEDULED` whose `leg_class` is not `REPOSITIONING` — that is, every `REVENUE` and every `MAINTENANCE_FERRY` leg — is cancelled into `CANCELLED_LESSOR` with `cancelling_party` `LESSOR` and `cancel_reason` `COMMERCIAL`, each cancellation recomputing crew exposure and the covering month's charge; repositioning legs are deliberately spared so the ferry to the redelivery station can still be flown. Every `OPEN` utilization period on the lease is closed into `PENDING_SETTLEMENT` with the `FINAL` variant fields written. And a `ReturnCondition` record is created for the lease against the airframe that is the lease's `primary_aircraft_id` at that moment, with `status` `PENDING_INSPECTION`, `discrepancy_codes` empty, `discrepancy_cost_cents` 0, `billed_to_lessee_cents` 0 and `repositioning_leg_id` null. Its `status` will travel `PENDING_INSPECTION`, `DISCREPANCIES_OPEN`, `CLEARED` and the terminal `CLOSED`.

**Inspection.** Technical control records the redelivery inspection by supplying `hours_since_check_at_return`, `cycles_since_check_at_return`, `fuel_on_board_kg` and a `discrepancy_codes` array of ATA-style codes noted on the airframe. Inspection is admissible while the record is `PENDING_INSPECTION` or `DISCREPANCIES_OPEN` — a re-inspection is expected and supported — and, on a first inspection, requires the lease to be `TERMINATING`. All four readings are stored.

The discrepancy charge is then priced. The hours overrun is the amount by which `hours_since_check_at_return` exceeds the lease's `return_hours_since_check_max`, floored at zero. The cycles overrun is the amount by which `cycles_since_check_at_return` exceeds `return_cycles_since_check_max`, floored at zero. The fuel shortfall is the amount by which `fuel_on_board_kg` falls below `return_fuel_kg_required`, floored at zero. The airframe component is the hours overrun multiplied by a rate of 2,500 cents (USD 25.00) per hour over, rounded half up to whole cents — this being the only one of the three that needs rounding, since the other two multiply integers. The cycles component is the cycles overrun multiplied by a rate of 18,000 cents (USD 180.00) per cycle over. The fuel component is the fuel shortfall multiplied by a rate of 95 cents per kilogram short. Their raw sum is then capped at the lease's `return_liability_cap_cents`.

Two rules finish the pricing. If the raw sum is 0 *and* `discrepancy_codes` is empty, `discrepancy_cost_cents` is 0. Otherwise `discrepancy_cost_cents` is the greater of the capped sum and a minimum discrepancy fee of 250,000 cents (USD 2,500.00) — a recorded discrepancy code always attracts at least that minimum, even when nothing measurable was over.

The deposit waterfall follows. `return_deposit_applied_cents` on the lease becomes the lesser of `discrepancy_cost_cents` and the lease's full `return_deposit_cents`; `return_deposit_remaining_cents` becomes `return_deposit_cents` less that applied figure; and `billed_to_lessee_cents` on the return record becomes `discrepancy_cost_cents` less the applied figure. The waterfall always starts from the full original `return_deposit_cents` and never from the surviving remainder of an earlier inspection, which is what makes re-inspection safe and keeps the deposit invariant of §2.9 true at every step.

A first inspection producing a non-empty `discrepancy_codes` array moves the record from `PENDING_INSPECTION` to `DISCREPANCIES_OPEN`. A first inspection with an empty or omitted `discrepancy_codes` array and a computed discrepancy cost of 0 moves it from `PENDING_INSPECTION` to `CLEARED`, writing the recorded return metrics and leaving the deposit untouched. A re-inspection with an empty `discrepancy_codes` array moves the record from `DISCREPANCIES_OPEN` to `CLEARED`, recomputing the cost and re-applying the waterfall from the original deposit balance.

**Closure.** Operations control closes the return record by supplying the `repositioning_leg_id` of the ferry leg. Closure is admissible only once the record is `CLEARED`: attempted while it is still `DISCREPANCIES_OPEN` it is refused with `ERR_RETURN_DISCREPANCIES_OPEN` (HTTP 409), and attempted while it is still `PENDING_INSPECTION` or already `CLOSED` it is refused with `ERR_RETURN_CONDITION_INVALID_STATE` (HTTP 409). The named leg must be a leg on the same lease whose `leg_class` is `REPOSITIONING`, whose `status` is `COMPLETED` and whose `dest_icao` equals the lease's `redelivery_icao`; anything else is refused with `ERR_REPOSITIONING_LEG_INCOMPLETE` (HTTP 409).

Closure stores `repositioning_leg_id`, moves the record from `CLEARED` to the terminal `CLOSED`, and drives the lease from `TERMINATING` to the terminal `RETURNED`. That final lease transition releases the airframe — clearing its `assigned_lease_id` and moving its `status` from `ASSIGNED` to `AVAILABLE` — and sets every `CrewQualification` on the lease to `REVOKED`. The arrangement is then complete: the receivable stands at whatever the issued invoices total, the deposit split is final, and the airframe is back in the pool.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — registering a lessee, an airframe or a crew member, drafting a lease, filing a docket, attaching a certificate, enrolling a qualification, scheduling a leg, requesting a substitution, preparing an invoice, filing a reliability report, or serving termination (which creates the return-conditions record) — return `201 Created`. Every operation that modifies an existing resource, and every read, returns `200 OK`. Request and response payloads are not reproduced here; the fields each operation accepts and the state it writes are specified in the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wetlease/lessees` | Register a lessee taking ACMI capacity | BillingAdmin |
| GET | `/wetlease/lessees/{lesseeId}` | Fetch one lessee with its recomputed receivable | BillingAdmin, LessorOpsController, Lessee |
| POST | `/wetlease/lessees/{lesseeId}/suspend` | Apply a credit-control suspension | BillingAdmin |
| POST | `/wetlease/lessees/{lesseeId}/reinstate` | Lift a credit-control suspension | BillingAdmin |
| POST | `/wetlease/aircraft` | Add an airframe to the lessor fleet | MaintenanceController |
| GET | `/wetlease/aircraft/{aircraftId}` | Fetch one airframe with counters and lease assignment | MaintenanceController, LessorOpsController, Lessee |
| GET | `/wetlease/aircraft` | List airframes | MaintenanceController, LessorOpsController, Lessee |
| POST | `/wetlease/aircraft/{aircraftId}/maintenance-events` | Record a ground, return-to-service or retire event | MaintenanceController |
| POST | `/wetlease/crew-members` | Register a lessor crew member | LessorOpsController |
| GET | `/wetlease/crew-members/{crewMemberId}` | Fetch one crew member with recomputed rolling exposure | LessorOpsController, MaintenanceController |
| POST | `/wetlease/leases` | Draft an ACMI wet lease | LessorOpsController |
| GET | `/wetlease/leases/{leaseId}` | Fetch one lease agreement | LessorOpsController, BillingAdmin, MaintenanceController, RegulatoryAuthority, InsuranceUnderwriter, Lessee |
| GET | `/wetlease/leases` | List lease agreements | LessorOpsController, BillingAdmin, RegulatoryAuthority, Lessee |
| POST | `/wetlease/leases/{leaseId}/submit-for-approval` | File the arrangement with the authority | LessorOpsController |
| POST | `/wetlease/leases/{leaseId}/activate` | Bring the lease into force, or reactivate it | LessorOpsController |
| POST | `/wetlease/leases/{leaseId}/terminate` | Serve termination and open the return record | LessorOpsController |
| POST | `/wetlease/leases/{leaseId}/withdraw` | Withdraw a lease that never entered service | LessorOpsController |
| GET | `/wetlease/leases/{leaseId}/regulatory-approvals` | List the authority dockets filed against this lease | RegulatoryAuthority, LessorOpsController, Lessee |
| GET | `/wetlease/leases/{leaseId}/insurance-certificates` | List the certificates attached to this lease | InsuranceUnderwriter, LessorOpsController, Lessee |
| GET | `/wetlease/regulatory-approvals/{approvalId}` | Fetch one authority docket | RegulatoryAuthority, LessorOpsController, Lessee |
| GET | `/wetlease/regulatory-approvals` | List authority dockets | RegulatoryAuthority, LessorOpsController, Lessee |
| POST | `/wetlease/regulatory-approvals/{approvalId}/decision` | Record a determination on the docket | RegulatoryAuthority |
| POST | `/wetlease/regulatory-approvals/{approvalId}/clear-conditions` | Clear named condition codes | RegulatoryAuthority |
| POST | `/wetlease/regulatory-approvals/{approvalId}/revoke` | Revoke the determination | RegulatoryAuthority |
| POST | `/wetlease/insurance-certificates` | Attach a certificate of insurance to a lease | InsuranceUnderwriter |
| GET | `/wetlease/insurance-certificates/{certificateId}` | Fetch one insurance certificate | InsuranceUnderwriter, LessorOpsController, Lessee |
| GET | `/wetlease/insurance-certificates` | List insurance certificates | InsuranceUnderwriter, LessorOpsController, Lessee |
| POST | `/wetlease/insurance-certificates/{certificateId}/revoke` | Pull cover, heading the insurance-lapse cascade | InsuranceUnderwriter |
| POST | `/wetlease/crew-qualifications` | Enrol a crew member in lessee-procedures training | LessorOpsController |
| GET | `/wetlease/crew-qualifications/{qualificationId}` | Fetch one crew qualification record | LessorOpsController, MaintenanceController, Lessee |
| GET | `/wetlease/crew-qualifications` | List crew qualifications | LessorOpsController, MaintenanceController, Lessee |
| POST | `/wetlease/crew-qualifications/{qualificationId}/complete-checkride` | Record the differences-training checkride | LessorOpsController |
| POST | `/wetlease/flight-legs` | Schedule a leg under the lease | LessorOpsController |
| GET | `/wetlease/flight-legs/{legId}` | Fetch one leg with its computed minute figures | LessorOpsController, MaintenanceController, BillingAdmin, Lessee |
| GET | `/wetlease/flight-legs` | List flight legs | LessorOpsController, MaintenanceController, BillingAdmin, Lessee |
| POST | `/wetlease/flight-legs/{legId}/dispatch` | Release the leg for departure | LessorOpsController |
| POST | `/wetlease/flight-legs/{legId}/complete` | Close out the leg on block-in | LessorOpsController |
| POST | `/wetlease/flight-legs/{legId}/cancel` | Cancel a scheduled or dispatched leg | LessorOpsController |
| POST | `/wetlease/substitutions` | Request a substitute airframe | LessorOpsController |
| GET | `/wetlease/substitutions/{substitutionId}` | Fetch one substitution request | LessorOpsController, MaintenanceController, Lessee |
| GET | `/wetlease/substitutions` | List substitution requests | LessorOpsController, MaintenanceController, Lessee |
| POST | `/wetlease/substitutions/{substitutionId}/consent` | Grant or withhold lessee consent | Lessee |
| POST | `/wetlease/substitutions/{substitutionId}/effectuate` | Swap the airframe and re-point affected legs | LessorOpsController |
| GET | `/wetlease/utilization-periods/{periodId}` | Fetch one utilization period with its charge components | BillingAdmin, LessorOpsController, Lessee |
| GET | `/wetlease/utilization-periods` | List utilization periods | BillingAdmin, LessorOpsController, Lessee |
| GET | `/wetlease/utilization-periods/{periodId}/settlement-preview` | Non-mutating both-variant settlement preview | BillingAdmin, LessorOpsController, Lessee |
| POST | `/wetlease/utilization-periods/{periodId}/close` | Close the month under the final variant | BillingAdmin |
| POST | `/wetlease/utilization-periods/{periodId}/dispute` | Dispute a settled month | Lessee |
| POST | `/wetlease/utilization-periods/{periodId}/resolve-dispute` | Reopen or uphold a disputed settlement | BillingAdmin |
| POST | `/wetlease/settlement-invoices` | Prepare the block-hour settlement invoice | BillingAdmin |
| GET | `/wetlease/settlement-invoices/{invoiceId}` | Fetch one settlement invoice | BillingAdmin, LessorOpsController, Lessee |
| GET | `/wetlease/settlement-invoices` | List settlement invoices | BillingAdmin, LessorOpsController, Lessee |
| POST | `/wetlease/settlement-invoices/{invoiceId}/approve` | Second-pair-of-eyes approval | BillingAdmin |
| POST | `/wetlease/settlement-invoices/{invoiceId}/issue` | Issue the invoice to the lessee | BillingAdmin |
| POST | `/wetlease/settlement-invoices/{invoiceId}/void` | Void a prepared, approved or issued invoice | BillingAdmin |
| POST | `/wetlease/reliability-reports` | File the monthly technical-dispatch-reliability report | MaintenanceController |
| GET | `/wetlease/reliability-reports/{reportId}` | Fetch one reliability report with both bases | MaintenanceController, BillingAdmin, LessorOpsController, Lessee |
| GET | `/wetlease/reliability-reports` | List reliability reports | MaintenanceController, BillingAdmin, LessorOpsController, Lessee |
| POST | `/wetlease/reliability-reports/{reportId}/review` | Accept or reject the filed report | Lessee |
| GET | `/wetlease/return-conditions/{returnId}` | Fetch one return-conditions record | LessorOpsController, MaintenanceController, BillingAdmin, Lessee |
| GET | `/wetlease/return-conditions` | List return-conditions records | LessorOpsController, MaintenanceController, BillingAdmin, Lessee |
| POST | `/wetlease/return-conditions/{returnId}/inspect` | Record the redelivery inspection and price discrepancies | MaintenanceController |
| POST | `/wetlease/return-conditions/{returnId}/close` | Close the return once cleared and repositioned | LessorOpsController |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock | LessorOpsController, BillingAdmin, MaintenanceController, InsuranceUnderwriter, RegulatoryAuthority |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_LESSEE_NOT_FOUND` | 404 Not Found |
| `ERR_AIRCRAFT_NOT_FOUND` | 404 Not Found |
| `ERR_LEASE_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_QUALIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_APPROVAL_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_LEG_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSTITUTION_NOT_FOUND` | 404 Not Found |
| `ERR_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_CONDITION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_PERIOD_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LEASE_VERSION` | 412 Precondition Failed |
| `ERR_PERIOD_NOT_READY_FOR_SETTLEMENT` | 409 Conflict |
| `ERR_LESSEE_INVALID_STATE` | 409 Conflict |
| `ERR_LEASE_INVALID_STATE` | 409 Conflict |
| `ERR_APPROVAL_INVALID_STATE` | 409 Conflict |
| `ERR_LEG_INVALID_STATE` | 409 Conflict |
| `ERR_SUBSTITUTION_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_INVALID_STATE` | 409 Conflict |
| `ERR_PERIOD_INVALID_STATE` | 409 Conflict |
| `ERR_RETURN_CONDITION_INVALID_STATE` | 409 Conflict |
| `ERR_AIRCRAFT_UNAVAILABLE` | 409 Conflict |
| `ERR_CREW_NOT_TYPE_RATED` | 422 Unprocessable Entity |
| `ERR_CREW_DUTY_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_CREW_BLOCK_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES` | 409 Conflict |
| `ERR_REGULATORY_APPROVAL_MISSING` | 409 Conflict |
| `ERR_OPERATIONAL_CONTROL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSURANCE_COVERAGE_MISSING` | 409 Conflict |
| `ERR_INSURANCE_LIMIT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_INSURANCE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_LEG_OUTSIDE_LEASE_TERM` | 422 Unprocessable Entity |
| `ERR_AIRCRAFT_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_TAIL_NUMBER` | 409 Conflict |
| `ERR_MAINTENANCE_PROGRAM_MISALIGNED` | 422 Unprocessable Entity |
| `ERR_SUBSTITUTION_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SUBSTITUTION_CONSENT_REQUIRED` | 403 Forbidden |
| `ERR_NO_SUBSTITUTE_AIRCRAFT_AVAILABLE` | 409 Conflict |
| `ERR_RELIABILITY_REPORT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_LESSEE_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_LESSEE_SUSPENDED` | 403 Forbidden |
| `ERR_RETURN_DISCREPANCIES_OPEN` | 409 Conflict |
| `ERR_REPOSITIONING_LEG_INCOMPLETE` | 409 Conflict |
