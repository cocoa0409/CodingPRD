# USDA Farm Program Enrollment API — Product Requirements Document

## 1. Introduction

The Farm Service Agency administers federal farm programs at the county level, where producers enroll their operations for price and revenue support under Agriculture Risk Coverage and Price Loss Coverage. County offices today manage this work across paper forms, spreadsheets, and phone calls: farm serial numbers are tracked in filing cabinets, base acreage is reconciled by hand when tracts are divided or combined, and each year's acreage report is compared against an inflexible deadline that producers routinely miss. Payment eligibility depends on adjusted gross income attestation and conservation compliance — two separate records held in two separate files, checked only when a county specialist remembers to look.

This document specifies a unified API for the full enrollment lifecycle, mounted under `/fsa`. It begins with the standing record of the farm itself — the serial number, the county that administers it, the tracts and fields that carry its base acres — and proceeds through acreage reporting, program election between price-loss and revenue-loss coverage, one-time yield updates drawn from a five-year production history, and the enrollment contract that ties all of these together for a single crop year. Disaster applications and appeals sit alongside the mainline flow, each with its own review chain and its own downstream effects on payment.

Payment computation is the system's most consequential act: two different statutory formulas (price-triggered versus revenue-triggered), layered under a per-producer payment limitation, an adjusted gross income eligibility bar, a late-filing reduction, and a federal sequestration withholding. The county committee certifies, the county executive director approves and disburses, and no one who filed a record may be the one who signs off on it. Every rule in this document exists to make that chain reproducible, auditable, and fair to the producer.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role named in `X-User-Role` is not permitted to invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Four roles exist:

- `Producer` — a farmer or operator acting on their own farm records. When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting `Producer`; ownership checks on any resource that references a `Producer` compare the resource's foreign-key field to `X-User-ID`.
- `CountySpecialist` — FSA county office program specialist handling record keeping and certification preparation. When `X-User-Role` is `CountySpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `CountyExecutiveDirector` — the CED, who approves enrollments, issues payments, assigns reviewers, and handles exceptions. When `X-User-Role` is `CountyExecutiveDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `CountyCommittee` — an elected county committee member who performs final certification and adjudication. When `X-User-Role` is `CountyCommittee`, `X-User-ID` is the `id` of the acting `Producer` (committee reviewers are themselves producers); ownership and segregation-of-duties checks compare resource foreign-key fields to `X-User-ID`.

All four roles may perform reads (any `GET`). Write capabilities are partitioned by role as described throughout §3 and summarized in §4.

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

List endpoints accept `limit` and `offset` query parameters. The default `limit` is 10; the minimum is 1 and the maximum is 100. The default `offset` is 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. Results are sorted by `created_at` ascending. The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix. Resources additionally carry `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and an integer `version` that increments on each mutation. One entity is exempt from the full common-fields contract: `YieldObservation` carries only `id` and `created_at`; both `updated_at` and `version` are absent on `YieldObservation`. All other entities (Farm, Producer, FarmMembership, Tract, Field, AcreageReport, AcreageReportLine, ProgramElection, YieldRecord, Enrollment, DisasterApplication, Appeal) carry the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Precision, Rounding, and Money

Monetary amounts inside entity fields are stored as integer cents (for example, `payment_limitation_cap_cents`, `computed_payment_cents`, `sequestration_cents`). Payment calculations and payment-derivation steps round half-up to 2 decimal places; the APH yield calculation rounds half-up to 1 decimal place. Numeric acreage fields carry two-decimal precision where applicable (for example, `base_acres`).

### 2.6. Optimistic Concurrency Control

Two write endpoints are OCC-guarded, both against the `Farm` aggregate:

- Creating a program election on a farm requires `expected_farm_version` as a non-optional request field carrying the client's last observed `version` of the target `Farm`. If the farm's current `version` has advanced past that value, the request is rejected with `ERR_STALE_FARM_VERSION` (HTTP 412).
- Opening a reconstitution on a farm likewise requires `expected_farm_version`. A mismatch with the farm's current `version` is rejected with `ERR_STALE_FARM_VERSION` (HTTP 412).

Endpoints not listed above do not take a version field. The OCC check runs after state validation and before the business-rule validation, except where an endpoint notes a specific precondition order (the election-creation membership check in §3.4 runs before it); it is the mechanism that prevents a client from acting on a farm record it has not observed.

### 2.7. Nested Resource Retrieval and Existence Checking

URLs that traverse the Farm → Tract → Field hierarchy (or any other parent-child path) validate path parameters left to right. Every path id and every foreign key referenced in the request body must resolve to an existing entity; any unresolvable reference is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.8. Validation Priority

When multiple validations could fire on the same request, they are evaluated in a fixed order. Authentication (presence and well-formedness of `X-User-ID` and `X-User-Role`) runs first, then role authorization, then existence resolution of every path id and body foreign key, then the state-machine check that the target resource is in a state from which the requested transition is defined, then the OCC stale-farm-version check where applicable, then temporal gates (acreage reporting deadline, election window), then business safety gates (conservation compliance, AGI eligibility), then referential business rules (active election present, acreage certified), then business constraints (segregation of duties, cropland capacity, share-percent sum, base-acre conservation, yield update window), then fiscal gates (disaster loss threshold, payment limitation), and finally request-shape validation (required fields present, well-typed values, declared enum members — `ERR_INVALID_REQUEST`, HTTP 400). The ordering matters because it determines which error a multi-violation request surfaces: a request that is both unauthenticated and malformed returns `ERR_UNAUTHENTICATED`; a request that is stale-versioned and also violates the share sum returns `ERR_STALE_FARM_VERSION`. Within a handler, request-shape validation is applied as the request body is consumed, so a missing or ill-typed required field surfaces `ERR_INVALID_REQUEST` at the point of consumption rather than strictly after every other rule category.

### 2.9. The Logical Clock

All deadline and window checks in this system read a logical clock, not wall-clock time. A specialist-driven test-driving capability sets the logical clock to a supplied `to_iso8601` instant — any parseable ISO 8601 timestamp, earlier or later than the current reading; an unparseable value is rejected with `ERR_INVALID_REQUEST` — and returns an object carrying `current_utc`, the new logical reading. The server's startup default is `2026-08-01T00:00:00Z`; before any clock-setting call the clock reads exactly this default and never falls back to wall-clock time.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Farm Record

A `CountySpecialist` opens a new farm record by supplying the FSA-assigned `farm_number` (unique within the administering county), the 3-digit FIPS `county_code`, the `program_year` the record belongs to, and optionally the `arc_co_ic_indicator` (one of `COUNTY` or `INDIVIDUAL`; when omitted the farm defaults to `COUNTY`). The new farm starts in `ACTIVE` `farm_status`, and its `total_base_acres` — a computed sum across the farm's `ACTIVE` tracts — begins at zero until tracts are added. Farms may be listed with optional `county_code` and `program_year` filters, and read by any role.

Tracts are added to the farm by a specialist providing `tract_number`, the historical `base_acres` for the tract (zero or more, two-decimal precision), and the `cropland_acres` ceiling that reported fields may not exceed. Each new tract starts `ACTIVE` under `tract_status`, and its `reconstituted_from_tract_id` is null on original tracts. Adding a tract triggers recomputation of the farm's `total_base_acres`. Fields are added to a tract by referencing the parent's `tract_id` and supplying a `field_number` and a GIS-measured `acres`; the sum of `acres` across all fields on a tract must not exceed that tract's `cropland_acres`, or the request is rejected with `ERR_CROPLAND_EXCEEDED`.

Producers are registered separately by a specialist, who supplies `producer_name`, the `tax_id_last4` used for attribution matching, and an `entity_type` of `INDIVIDUAL`, `CORPORATION`, `PARTNERSHIP`, `TRUST`, or `LLC`. A new producer starts with `agi_attestation_status` set to `NOT_FILED`, `adjusted_gross_income` null, `conservation_status` set to `PENDING`, and `payment_limitation_cap_cents` at the statutory default of 12500000 (that is, $125,000.00). Producers may be listed filtered by `entity_type`.

A producer is joined to a farm through a `FarmMembership`, created by a specialist with `producer_id`, `share_percent` (strictly greater than zero and at most 100; an out-of-range value is likewise rejected with `ERR_SHARE_SUM_INVALID`), and an optional `is_spouse_pair` flag (defaulting to false). The share percentages across a farm's `ACTIVE` memberships must sum to exactly 100.00 after the add; a membership that would break this invariant is rejected with `ERR_SHARE_SUM_INVALID`. Memberships begin `ACTIVE` under `membership_status`; removing one (a specialist action returning no content) transitions it to `REMOVED`, and the removal is not state-guarded — removing an already-`REMOVED` membership succeeds again with no content. When two `ACTIVE` memberships on a farm are flagged `is_spouse_pair`, each flagged member's producer has `payment_limitation_cap_cents` raised to 25000000. Memberships may be listed filtered by `producer_id` or `farm_id`, and tracts may be listed filtered by `farm_id` or `reconstituted_from_tract_id`.

### 3.2. AGI Attestation and Conservation Compliance

Before any enrollment can be approved, a producer must clear two independent compliance gates.

The AGI gate begins when a producer files an attestation carrying `adjusted_gross_income` — the producer's three-year average AGI in whole dollars. The attested value must be a non-negative integer; the filing transitions `agi_attestation_status` from `NOT_FILED` to `FILED`. Filing is defined only from `NOT_FILED` or `NONCOMPLIANT`; an attempt from `FILED` or `VERIFIED` is rejected with `ERR_INVALID_STATE`. A county specialist then either verifies the attestation (moving it to `VERIFIED`) or flags it (moving it to `NONCOMPLIANT`); both actions require `FILED` and otherwise fail with `ERR_INVALID_STATE`. A producer flagged `NONCOMPLIANT` may re-file; the re-filing moves the status back to `FILED` and restarts verification.

The conservation gate tracks HELC/WC self-certification. From `PENDING`, a producer files a conservation certification and moves to `CERTIFIED`; from `VIOLATION`, a producer may be re-certified only when a remediation plan attestation accompanies the certification — the optional `remediation_plan` field on the certification request carries it, and its absence on re-certification from `VIOLATION` is rejected with `ERR_INVALID_REQUEST`. Filing a certification from any other status is rejected with `ERR_INVALID_STATE`. A `CountyExecutiveDirector` records a conservation violation by supplying a `violation_code`, which moves `conservation_status` from `CERTIFIED` to `VIOLATION` (a violation recording from any other status is rejected with `ERR_INVALID_STATE`); no enrollment records are modified — the violation blocks payment indirectly, because the conservation gate at CED-approval time reads the producer's current status. The CED may also grant an exemption by supplying an `exemption_reason`; the exemption moves `PENDING` to `EXEMPT` (from any other status the request is rejected with `ERR_INVALID_STATE`), and the server does not condition the exemption on the producer's entity type.

### 3.3. Acreage Reporting

A producer opens an acreage report for a farm by supplying the `program_year`; the report starts in `DRAFT` under `report_status`. Lines are then added to the report, one per field: each line carries the `acreage_report_id` of its parent report, the `field_id` being reported, the `crop_code` (such as `CORN`, `SOYBN`, `WHEAT`, or `COTTON`), `planted_acres` (zero or more), `prevented_planted_acres` (zero or more), and an `intended_use` of `GRAIN`, `SILAGE`, `HAY`, `GRAZE`, or `COVER`. Lines may be added only while the report is `DRAFT`; an append to a non-`DRAFT` report is rejected with `ERR_INVALID_STATE`, and a negative `planted_acres` or `prevented_planted_acres` is rejected with `ERR_INVALID_REQUEST`. On a single line, the sum of `planted_acres` and `prevented_planted_acres` must not exceed the parent field's `acres`; violations are rejected with `ERR_LINE_ACRES_EXCEED_FIELD`. Each line added recomputes the report's `reported_acres`, the running sum of each line's `planted_acres` plus `prevented_planted_acres`.

Filing the report is deadline-aware. For the 2026 crop year the reporting deadline is `2026-07-15T23:59:59Z`. A producer who holds an `ACTIVE` membership on the report's farm may file while the logical clock is at or before the deadline, provided every line's field belongs to the report's farm and `reported_acres` is greater than zero. Filing evaluates its preconditions in order — the report must be `DRAFT` (else `ERR_INVALID_STATE`), the producer must hold the membership (else `ERR_INVALID_REQUEST`), every line's field must belong to the report's farm (else `ERR_INVALID_REQUEST`), and `reported_acres` must exceed zero (else `ERR_INVALID_REQUEST`) — before the deadline gate is consulted. Filing stamps `filed_at` from the logical clock, records the filer's producer id in `filed_by_producer_id`, and moves the report from `DRAFT` to `FILED`. When the clock has passed the deadline but remains within 30 days after it, filing instead moves the report to `LATE_FILED`, stamps `filed_at`, and accepts a late fee — a `LATE_FILED` report carries a downstream payment reduction of ten percent. Once the clock is beyond the deadline plus the 30-day late window, filing is rejected outright with `ERR_ACREAGE_DEADLINE_PASSED`.

A county specialist certifies a `FILED` or `LATE_FILED` report, moving it to `CERTIFIED` — but only if the specialist did not file the report, a segregation-of-duties rule whose violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. A specialist may also reject a `FILED` or `LATE_FILED` report outright by supplying a `reason`, moving it to `REJECTED` (a terminal state). A `CERTIFIED` report can be reopened back to `FILED` by a specialist, but only while no enrollment for the same farm and year is in `CERTIFIED`, `PAYMENT_COMPUTED`, `PAYMENT_ISSUED`, `ON_APPEAL`, or `REMANDED`; a blocking enrollment — like attempting any transition the report's current state does not define — is rejected with `ERR_INVALID_STATE`. Acreage reports may be listed for a farm filtered by `program_year`.

### 3.4. Program Elections

For each covered commodity on a farm, the producer elects between price-loss and revenue-loss coverage by creating a program election with the `program_year`, the `commodity` (one of `CORN`, `SOYBN`, `WHEAT`, `COTTON`), and an `election_code` of `PLC`, `ARC_CO`, or `ARC_IC`. The election window for the 2026 crop year closes at `2026-03-16T23:59:59Z`; creating, superseding, or withdrawing an election once the clock is past that deadline is rejected with `ERR_ELECTION_WINDOW_CLOSED`.

Creating an election is an OCC-guarded write against the farm: the request must carry `expected_farm_version` matching the farm's current `version`, and a mismatch is rejected with `ERR_STALE_FARM_VERSION`. The producer must hold an `ACTIVE` membership on the farm — a check that runs before the OCC version check and surfaces `ERR_INVALID_REQUEST` on failure. When an election is created for a farm, year, and commodity that already has an `ACTIVE` election, the prior election moves to `SUPERSEDED`. On every creation, whether or not a prior election existed, the new election records `effective_from_version` equal to the farm's current `version` and the farm's `version` then increments by one. Supersession is permitted only while no enrollment referencing the prior election has reached `CERTIFIED` or beyond — that is, `CERTIFIED`, `PAYMENT_COMPUTED`, `PAYMENT_ISSUED`, `ON_APPEAL`, or `REMANDED` — and a blocked supersession is rejected with `ERR_INVALID_STATE`. Elections may be listed for a farm filtered by `program_year` or `commodity`.

A producer may withdraw an `ACTIVE` election, moving it to `WITHDRAWN` (terminal), provided the election window is still open and no enrollment referencing the election has reached `CERTIFIED` or beyond (a referencing enrollment surfaces `ERR_INVALID_STATE`). Separately, when an enrollment that pinned an election reaches `CERTIFIED`, the system moves that election to `LOCKED` — terminal and immutable. Elections begin in `ACTIVE` under `election_status`.

### 3.5. Yield Records and Actual Production History

A county specialist creates a yield record for a farm by supplying the `commodity`. The record starts `PROVISIONAL` under `yield_status`, with `update_window_open` set to true, and its `aph_yield_bu_per_acre` computed immediately from whatever observations exist.

Observations are appended by a specialist, each carrying the `yield_record_id` of its parent, a `crop_year` (any integer; no range validation is applied — the trailing-five-year window is imposed at APH computation time), and an optional `actual_yield_bu_per_acre` — a null value signals a plug year with no evidence. Each observation's `is_disaster_substituted` flag starts false. Appends are accepted in any `yield_status` except `LOCKED`, where they are rejected with `ERR_INVALID_STATE`. Observations on a record are listed ordered by `crop_year` ascending rather than the default `created_at` ordering.

The APH yield is a weighted average over the trailing five years of observations, ordered by `crop_year` ascending. When more than one observation exists for the same `crop_year`, only the most recently appended observation for that year participates — this is how an actual value appended for a year that previously held only a plug entry replaces the plug — so the average runs over one observation per `crop_year` across the trailing five `crop_year`s represented. Each observation contributes an effective yield: when the observation carries an actual value and has not been disaster-substituted, the effective yield is that actual value; when the observation has been disaster-substituted, the effective yield is sixty-five percent of the commodity's T-yield; when the observation's actual value is null, the effective yield is the commodity's plug yield. The T-yields are 180 bushels per acre for `CORN`, 50 for `SOYBN`, and 65 for `WHEAT`; the plug yields are 135 for `CORN`, 37 for `SOYBN`, and 49 for `WHEAT`; a commodity with no defined T-yield or plug yield (such as `COTTON`) contributes zero for a plug year and is ineligible for disaster substitution. The trailing five years are the five greatest `crop_year` values represented among the record's observations. The `aph_yield_bu_per_acre` is the sum of the five effective yields divided by five, rounded half-up to one decimal place; when fewer than five crop years are represented the sum runs over those present while the divisor remains five, and a record with no observations computes to 0.0. The APH recomputes on yield-record creation, on each observation append, on the one-time update, and when a disaster approval substitutes yields.

A producer who holds an `ACTIVE` membership on the record's farm (holding none surfaces `ERR_INVALID_REQUEST`) may trigger the one-time APH update while `update_window_open` remains true. From `PROVISIONAL` the update moves the record to `UPDATED`, recomputes `aph_yield_bu_per_acre` from the current observations, and flips `update_window_open` to false. A record already `CERTIFIED` may take the same update path back to `UPDATED` — a recertification path available only while the window remains open — with the same recompute and window consumption. Once the window has been consumed, any further update attempt is rejected with `ERR_YIELD_UPDATE_WINDOW_CLOSED`, while an update attempt on a `LOCKED` record is rejected with `ERR_INVALID_STATE`. A specialist certifies an `UPDATED` record, moving it to `CERTIFIED`. Yield records may be listed for a farm filtered by `commodity`. When an enrollment that pinned a yield record reaches `CERTIFIED`, the system moves that record — from `PROVISIONAL`, `UPDATED`, or `CERTIFIED` — to `LOCKED`, where it becomes immutable. A provisional APH may contain plug-year values; a certified APH replaces plugs with observed values, typically producing a different (higher) yield.

### 3.6. Reconstitution: Dividing and Combining Tracts

When a farm's tract structure no longer matches its deeds, a county specialist opens a reconstitution by supplying a `method` of `DIVIDE` or `COMBINE`, the `source_tract_ids` being restructured, and the `product_specs` describing the product tracts (each spec carries `tract_number`, `base_acres`, and `cropland_acres`). A `DIVIDE` takes exactly one source tract and at least two product specs; a `COMBINE` takes one or more source tracts and exactly one product spec — violations of these shapes are rejected with `ERR_INVALID_REQUEST`. The request is OCC-guarded: `expected_farm_version` must match the farm's current `version`, with mismatches rejected as `ERR_STALE_FARM_VERSION`. Opening a reconstitution requires that the farm be `ACTIVE` and that no enrollment on the farm is in `CERTIFIED`, `PAYMENT_COMPUTED`, or `PAYMENT_ISSUED`. The farm moves from `ACTIVE` to `RECONSTITUTION_PENDING`, its `version` increments by one, the source tracts move to `DIVIDED` or `COMBINED` under `tract_status`, and the product tracts are created `ACTIVE` — for a `DIVIDE`, two or more product tracts each recording `reconstituted_from_tract_id` pointing at the source; for a `COMBINE`, a single product tract whose declared `base_acres` conserve the source sum (within the tolerance below) and whose `reconstituted_from_tract_id` points at the first source tract.

Because the product tracts are created `ACTIVE` at open time, the base-acre conservation check runs as part of the open request: the absolute difference between the sum of product `base_acres` and the sum of source `base_acres` must be no greater than 0.01 acres, and a failure rejects the open call with `ERR_BASE_ACRE_IMBALANCE` with no state changes applied. On success the farm moves to `RECONSTITUTED` and `total_base_acres` is recomputed; the open call returns HTTP 201 with the farm object extended by a `reconstitution_id` identifying the reconstitution (the id the cancel endpoint takes). `RECONSTITUTED` is informational; the farm returns to `ACTIVE` when a specialist finalizes the reconstitution, which increments the farm's `version` by one again. Alternatively, a specialist may cancel an opened reconstitution at any time before finalization — while the farm sits in `RECONSTITUTED` — which deletes the product tracts, restores the source tracts to `ACTIVE`, and returns the farm to `ACTIVE`.

A `CountyExecutiveDirector` may retire a farm — moving it from `ACTIVE` to `RETIRED`, the terminal state — only when every enrollment on the farm is in `DRAFT`, `VOID`, or `PAYMENT_ISSUED` and no open (non-terminal) appeal or disaster application exists, open meaning an appeal in `FILED`, `CED_REVIEW`, `COMMITTEE_HEARING`, or `REMANDED` or a disaster application in `DRAFT`, `FILED`, or `UNDER_REVIEW`; a retirement whose preconditions fail is rejected with `ERR_INVALID_STATE`. Retirement removes every `ACTIVE` membership on the farm, transitioning each to `REMOVED`.

### 3.7. Enrollment: Submission Through Certification

A producer opens an enrollment for a farm by supplying the `program_year` and the covered `commodity`; the enrollment starts in `DRAFT` under `enrollment_status`, with `pinned_election_id`, `pinned_yield_record_id`, `computed_payment_cents`, `sequestration_cents`, and `submitted_by_producer_id` all null. Enrollments may be listed for a farm filtered by `program_year` or `enrollment_status`.

Submitting the enrollment requires that the producer hold an `ACTIVE` membership on the farm (otherwise `ERR_INVALID_REQUEST`), that an `ACTIVE` program election exist for the same farm, year, and commodity (otherwise `ERR_NO_ACTIVE_ELECTION`), that a yield record exist for the same farm and commodity (otherwise `ERR_NOT_FOUND`), and that the farm's acreage report for the year be `CERTIFIED` (otherwise `ERR_ACREAGE_NOT_CERTIFIED`). Submission moves the enrollment from `DRAFT` to `SUBMITTED` and records the submitter in `submitted_by_producer_id`.

CED approval is the compliance gateway. The `CountyExecutiveDirector` approves a `SUBMITTED` enrollment only when two independent gates both pass, and only when the CED is not the submitting producer (segregation of duties, `ERR_SEGREGATION_OF_DUTIES`) — the segregation-of-duties check runs before the two gates, and both gates read the submitting producer's record. The conservation gate requires the producer's `conservation_status` to be `CERTIFIED` or `EXEMPT`; a failure surfaces `ERR_CONSERVATION_NOT_CERTIFIED`. The AGI gate requires the producer's `agi_attestation_status` to be `VERIFIED` and the attested `adjusted_gross_income` to be at most 90000000 cents — the statutory $900,000 AGI limit; a failure surfaces `ERR_AGI_INELIGIBLE`. Approval moves the enrollment from `SUBMITTED` to `CED_APPROVED`.

Certification is the county committee's act, and it is the point at which the enrollment pins its inputs. A `CountyCommittee` reviewer certifies a `CED_APPROVED` enrollment, provided the reviewer did not submit the enrollment. Certification sets `pinned_election_id` to the current `ACTIVE` election and `pinned_yield_record_id` to the current yield record — the most recently created yield record for the farm and commodity. If no `ACTIVE` election exists at certification time (for example at recertification, when the prior pin is already locked), the most recently created `LOCKED` election for the farm, year, and commodity is pinned instead, and if neither exists certification fails with `ERR_NO_ACTIVE_ELECTION`. The pinned election transitions to `LOCKED` and the pinned yield record transitions to `LOCKED`. The enrollment is now `CERTIFIED`.

### 3.8. Payment Computation and Issuance

Payment computation is performed by a county specialist on a `CERTIFIED` enrollment, moving it to `PAYMENT_COMPUTED`. The formula applied depends on the pinned election's `election_code`, and the compute request carries the market inputs: `national_my_price` always, plus `county_actual_yield` and `benchmark_revenue` when the pinned election is `ARC_CO` or `ARC_IC` (an `ARC_IC` election is computed with the same county formula and the same inputs).

Under `PLC` — Price Loss Coverage — payment triggers when the effective price falls below the statutory reference price. The reference prices are $4.10 per bushel for `CORN`, $9.00 for `SOYBN`, and $5.50 for `WHEAT`. The effective price is the supplied `national_my_price`; this system declares no loan-rate table, so no loan-rate cap applies. The payment rate is the greater of zero and the reference price minus the effective price (a commodity with no declared reference price, such as `COTTON`, is treated as reference price zero, so PLC never triggers for it). The base payment is the payment rate multiplied by the pinned yield record's current `aph_yield_bu_per_acre`, multiplied by the farm's current `total_base_acres`, multiplied by the statutory payment factor of 0.85. Identical acreage and yield inputs produce a non-zero payment when the effective price is below the reference price, and a zero payment at or above it.

Under `ARC_CO` — Agriculture Risk Coverage, county option — the guarantee is 86 percent of the supplied `benchmark_revenue`. Actual revenue is the supplied `county_actual_yield` multiplied by `national_my_price`. The payment rate is the lesser of ten percent of the benchmark revenue and the greater of zero and the guarantee minus actual revenue — the rate is capped at ten percent of benchmark. The base payment is the payment rate multiplied by the farm's current `total_base_acres`, multiplied by 0.85. ARC-CO keys off revenue (yield times price) where PLC keys off price alone, so the same farm data can produce a payment under one program and zero under the other when the price is low but county yield is high.

If the farm's acreage report for the year was filed late — its `filed_at` fell after the reporting deadline, so the report entered `LATE_FILED` at filing time — the base payment is then reduced by a factor of 0.90, a ten percent reduction for late filing. Certifying a late-filed report moves it to `CERTIFIED` but does not erase the reduction: it is the lateness of the filing, not the report's status at computation time (which is `CERTIFIED` on any computable enrollment), that triggers it. This reduction applies before payment limitation.

Payment limitation attributes the payment through the submitting producer's `ACTIVE` membership on the farm. The attributable amount is the base payment multiplied by the membership's `share_percent` divided by 100. The cap is the producer's `payment_limitation_cap_cents` converted to dollars; the standard cap is 12500000 cents ($125,000.00), raised to 25000000 cents ($250,000.00) when two memberships on a farm are flagged `is_spouse_pair`. The allowed amount is the lesser of the attributable amount and the cap; the disallowed remainder is attributable minus allowed. A computed payment that would exceed the producer's attributable cap is rejected with `ERR_PAYMENT_LIMITATION_EXCEEDED`, as is a computation whose submitting producer holds no `ACTIVE` membership on the farm.

Sequestration is the final withholding. The `sequestration_cents` amount is the post-limitation payment multiplied by 5.7 percent, rounded half-up to two decimal places. The net `computed_payment_cents` is the post-limitation payment minus the sequestration, rounded half-up to two decimal places. Both fields are set on the enrollment by the computation.

A `CountyExecutiveDirector` issues payment on a `PAYMENT_COMPUTED` enrollment, moving it to `PAYMENT_ISSUED` (terminal); disbursement itself is out of scope. A producer may void an enrollment while it is in `DRAFT` or `SUBMITTED`, moving it to `VOID` (terminal).

### 3.9. Disaster Applications

A producer opens a disaster application for a farm by supplying the `program_year`, a `disaster_type` of `DROUGHT`, `FLOOD`, `HAIL`, `FREEZE`, `WILDFIRE`, or `EXCESS_MOISTURE`, the `loss_acres` claimed, the `qualifying_commodity` the loss applies to, and optionally `documentation_complete` (defaulting to false) attesting that the Notice of Loss and evidence are on file. The application starts in `DRAFT` under `application_status`.

Filing the application requires that the producer hold an `ACTIVE` membership on the farm (otherwise `ERR_INVALID_REQUEST`) and that the farm's acreage report for the year be `CERTIFIED` (otherwise `ERR_INVALID_STATE`); filing moves the application from `DRAFT` to `FILED` and records the filer in `filed_by_producer_id`. A `CountyExecutiveDirector` then assigns a reviewer, moving the application to `UNDER_REVIEW` — but only when `documentation_complete` is true (otherwise `ERR_INVALID_STATE`). Disaster applications may be listed for a farm filtered by `program_year`.

Committee approval applies the thirty-five percent trigger: the claimed `loss_acres` must be at least thirty-five percent of the reported acres for the `qualifying_commodity` — reported acres being the sum of `planted_acres` plus `prevented_planted_acres` across the lines whose `crop_code` equals the `qualifying_commodity` on the farm's `CERTIFIED` acreage report for the year — an ELAP-style qualification gate whose failure is rejected with `ERR_LOSS_THRESHOLD_NOT_MET`. The committee reviewer must differ from the filer (`ERR_SEGREGATION_OF_DUTIES`). Approval moves the application to `APPROVED` and triggers a yield-substitution cascade: for each yield observation on the same farm and qualifying commodity whose actual yield is below sixty-five percent of the commodity's T-yield, `is_disaster_substituted` is set to true and sixty-five percent of the T-yield is substituted into the APH recompute, and every yield record that had an observation substituted recomputes its APH regardless of the record's status. A commodity with no defined T-yield (`COTTON`) undergoes no substitution cascade. The pinned yield record on any `CERTIFIED` enrollment for the same farm and commodity is re-evaluated, and if that enrollment is `PAYMENT_COMPUTED` or `PAYMENT_ISSUED` the payment delta is recomputed: the §3.8 computation is rerun using the same market inputs (`national_my_price`, and for `ARC_CO` also `county_actual_yield` and `benchmark_revenue`) that were supplied at the enrollment's payment computation — only the pinned APH has moved — and the resulting `computed_payment_cents` and `sequestration_cents` replace the prior values while the enrollment's status is left unchanged.

The committee may instead deny an `UNDER_REVIEW` application by supplying a `reason`, moving it to `DENIED` (terminal). A producer may withdraw an application while it is in `DRAFT` or `FILED`, moving it to `WITHDRAWN` (terminal).

### 3.10. Appeals and Recertification

A producer files an appeal against an enrollment determination by supplying the `farm_id`, the `enrollment_id` being appealed, a `ground_code` of `FACTUAL_ERROR`, `PROCEDURAL_ERROR`, `MISAPPLICATION_OF_RULE`, or `NEW_EVIDENCE`, and the `filed_by_producer_id` of the appellant. The enrollment must be in `CERTIFIED` or `PAYMENT_COMPUTED`; filing moves it to `ON_APPEAL`, remembering its prior state in `pre_appeal_status`. The appeal starts in `FILED` under `appeal_status`, with `assigned_reviewer_producer_id` and `remands_appeal_id` null. Appeals may be listed filtered by `farm_id`, `enrollment_id`, `remands_appeal_id`, `filed_by_producer_id`, or `assigned_reviewer_producer_id`, and for a farm filtered by `appeal_status`.

A `CountyExecutiveDirector` assigns the appeal to CED review, moving it from `FILED` to `CED_REVIEW`. When the CED cannot resolve the matter informally, the CED refers it to committee, supplying the `assigned_reviewer_producer_id` of a county-committee reviewer; the reviewer must differ from the appellant — the `assigned_reviewer_producer_id` must not equal `filed_by_producer_id` (a match is rejected with `ERR_SEGREGATION_OF_DUTIES`). Referral moves the appeal to `COMMITTEE_HEARING`.

From `COMMITTEE_HEARING` the committee has three dispositions, each requiring the reviewer to differ from the appellant (violations surface `ERR_SEGREGATION_OF_DUTIES`). Upholding moves the appeal to `UPHELD` (terminal) and returns the enrollment from `ON_APPEAL` to its prior state, `CERTIFIED` or `PAYMENT_COMPUTED`. Reversing — optionally carrying `corrected_payment_cents` — moves the appeal to `REVERSED` (terminal); when `corrected_payment_cents` is supplied the enrollment's `computed_payment_cents` is set to that value, and the enrollment is left in `ON_APPEAL`. Remanding moves the appeal to `REMANDED` and the enrollment to `REMANDED`, recording the appeal's id on the enrollment as `last_remanded_appeal_id`; the remand request carries `remand_instructions`.

A `REMANDED` enrollment may be recertified by the committee — the request carries no required fields — moving it back to `CERTIFIED` with its pins re-evaluated against current data as at certification (§3.7). From there the cycle can repeat: a later appeal re-opens the previously remanded case, and its `remands_appeal_id` records which earlier appeal it follows. The appellant may also close an appeal while it is in `FILED` or `CED_REVIEW`, moving it to `CLOSED` (terminal) and returning the enrollment to its pre-appeal state; only the appellant may close — a close by any other producer is rejected with `ERR_UNAUTHORIZED`.

## 4. Endpoint Definitions

New resources are returned with HTTP 201 on creation; actions that modify an existing resource return HTTP 200; removal of a membership returns HTTP 204 with no content. The producer sub-record filings (AGI attestation, conservation certification, conservation violation, conservation exemption) return the updated producer with HTTP 201. Error responses carry the HTTP status declared in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /fsa/farms | Create a farm record | CountySpecialist |
| GET | /fsa/farms/{farm_id} | Get farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/farms | List farms (paginated) | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/farms/{farm_id}/retire | Retire a farm (terminal) | CountyExecutiveDirector |
| POST | /fsa/producers | Register a producer | CountySpecialist |
| GET | /fsa/producers/{producer_id} | Get producer | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/producers | List producers | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/producers/{producer_id}/agi-attestations | File AGI attestation | Producer |
| POST | /fsa/producers/{producer_id}/agi-attestations/verify | Verify AGI attestation | CountySpecialist |
| POST | /fsa/producers/{producer_id}/agi-attestations/flag-noncompliant | Flag AGI noncompliant | CountySpecialist |
| POST | /fsa/producers/{producer_id}/conservation-certifications | File conservation compliance cert | Producer |
| POST | /fsa/producers/{producer_id}/conservation-violations | Record a conservation violation | CountyExecutiveDirector |
| POST | /fsa/producers/{producer_id}/conservation-exemptions | Grant conservation exemption | CountyExecutiveDirector |
| POST | /fsa/farms/{farm_id}/memberships | Add a producer to a farm with a share | CountySpecialist |
| GET | /fsa/farms/{id}/memberships | List memberships on a farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/memberships | List memberships filtered by producer or farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/memberships/{membership_id} | Get a membership | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| DELETE | /fsa/memberships/{membership_id} | Remove a membership | CountySpecialist |
| POST | /fsa/farms/{farm_id}/tracts | Add a tract to a farm | CountySpecialist |
| GET | /fsa/farms/{id}/tracts | List tracts on a farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/tracts/{tract_id} | Get a tract | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/tracts | List tracts filtered by farm or reconstitution source | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/tracts/{tract_id}/fields | Add a field to a tract | CountySpecialist |
| GET | /fsa/tracts/{id}/fields | List fields on a tract | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/fields/{field_id} | Get a field | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/fields/{id}/acreage-report-lines | List report lines referencing a field | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/farms/{farm_id}/reconstitutions | Open a reconstitution (DIVIDE or COMBINE); OCC-guarded | CountySpecialist |
| POST | /fsa/farms/{farm_id}/finalize-reconstitution | Finalize a balanced reconstitution | CountySpecialist |
| POST | /fsa/farms/{farm_id}/reconstitutions/{recon_id}/cancel | Cancel a pending reconstitution | CountySpecialist |
| POST | /fsa/farms/{farm_id}/acreage-reports | Open an acreage report | Producer |
| GET | /fsa/acreage-reports/{report_id} | Get acreage report | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/farms/{id}/acreage-reports | List reports for a farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/acreage-reports/{report_id}/lines | Add a line to a report | Producer |
| GET | /fsa/acreage-reports/{id}/lines | List lines on a report | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/acreage-reports/{report_id}/file | File the report (deadline-aware) | Producer |
| POST | /fsa/acreage-reports/{report_id}/certify | Certify a filed report (SoD) | CountySpecialist |
| POST | /fsa/acreage-reports/{report_id}/reject | Reject a report | CountySpecialist |
| POST | /fsa/acreage-reports/{report_id}/reopen | Reopen a certified report | CountySpecialist |
| POST | /fsa/farms/{farm_id}/program-elections | Create/supersede a program election (OCC-guarded) | Producer |
| GET | /fsa/program-elections/{election_id} | Get an election | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/program-elections/{id}/enrollments | List enrollments that pinned a given election | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/farms/{id}/program-elections | List elections for a farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/program-elections/{election_id}/withdraw | Withdraw an election while window open | Producer |
| POST | /fsa/farms/{farm_id}/yield-records | Create a yield record | CountySpecialist |
| GET | /fsa/yield-records/{record_id} | Get yield record | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/yield-records/{id}/enrollments | List enrollments that pinned a given yield record | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/farms/{id}/yield-records | List yield records for a farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/yield-records/{record_id}/observations | Append a yield observation | CountySpecialist |
| GET | /fsa/yield-records/{id}/observations | List observations on a record | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/yield-records/{record_id}/updates | Trigger one-time APH update | Producer |
| POST | /fsa/yield-records/{record_id}/certify | Certify a yield record | CountySpecialist |
| POST | /fsa/farms/{farm_id}/enrollments | Open an enrollment | Producer |
| GET | /fsa/enrollments/{enrollment_id} | Get enrollment | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/enrollments/{id}/appeals | List appeals against a given enrollment | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/farms/{id}/enrollments | List enrollments for a farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/enrollments/{enrollment_id}/submit | Submit an enrollment | Producer |
| POST | /fsa/enrollments/{enrollment_id}/ced-approve | CED approval (AGI + conservation gates) | CountyExecutiveDirector |
| POST | /fsa/enrollments/{enrollment_id}/certify | Committee certification (pins election+yield) | CountyCommittee |
| POST | /fsa/enrollments/{enrollment_id}/compute-payment | Compute payment (PLC or ARC-CO per pinned election) | CountySpecialist |
| POST | /fsa/enrollments/{enrollment_id}/issue-payment | Issue payment | CountyExecutiveDirector |
| POST | /fsa/enrollments/{enrollment_id}/recertify | Recertify after remand | CountyCommittee |
| POST | /fsa/enrollments/{enrollment_id}/void | Void an enrollment | Producer |
| POST | /fsa/farms/{farm_id}/disaster-applications | Open a disaster application | Producer |
| GET | /fsa/disaster-applications/{app_id} | Get disaster application | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/farms/{id}/disaster-applications | List disaster applications for a farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/disaster-applications/{app_id}/file | File disaster application | Producer |
| POST | /fsa/disaster-applications/{app_id}/assign-reviewer | Assign reviewer | CountyExecutiveDirector |
| POST | /fsa/disaster-applications/{app_id}/approve | Approve (35% threshold gate; SoD) | CountyCommittee |
| POST | /fsa/disaster-applications/{app_id}/deny | Deny | CountyCommittee |
| POST | /fsa/disaster-applications/{app_id}/withdraw | Withdraw | Producer |
| POST | /fsa/appeals | File an appeal | Producer |
| GET | /fsa/appeals/{appeal_id} | Get appeal | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/appeals | List appeals filtered by farm/enrollment/remand/filer/reviewer | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| GET | /fsa/farms/{id}/appeals | List appeals for a farm | Producer, CountySpecialist, CountyExecutiveDirector, CountyCommittee |
| POST | /fsa/appeals/{appeal_id}/assign-ced | Assign to CED | CountyExecutiveDirector |
| POST | /fsa/appeals/{appeal_id}/refer-to-committee | Refer to committee | CountyExecutiveDirector |
| POST | /fsa/appeals/{appeal_id}/uphold | Uphold original determination | CountyCommittee |
| POST | /fsa/appeals/{appeal_id}/reverse | Reverse determination | CountyCommittee |
| POST | /fsa/appeals/{appeal_id}/remand | Remand for recertification | CountyCommittee |
| POST | /fsa/appeals/{appeal_id}/close | Close (withdraw) an appeal | Producer |
| POST | /fsa/_clock/set_current_utc | Set the logical clock | CountySpecialist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_FARM_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ACREAGE_DEADLINE_PASSED | 422 |
| ERR_ELECTION_WINDOW_CLOSED | 422 |
| ERR_CONSERVATION_NOT_CERTIFIED | 422 |
| ERR_AGI_INELIGIBLE | 422 |
| ERR_NO_ACTIVE_ELECTION | 422 |
| ERR_ACREAGE_NOT_CERTIFIED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_CROPLAND_EXCEEDED | 422 |
| ERR_SHARE_SUM_INVALID | 422 |
| ERR_BASE_ACRE_IMBALANCE | 422 |
| ERR_LOSS_THRESHOLD_NOT_MET | 422 |
| ERR_PAYMENT_LIMITATION_EXCEEDED | 422 |
| ERR_LINE_ACRES_EXCEED_FIELD | 422 |
| ERR_YIELD_UPDATE_WINDOW_CLOSED | 422 |
